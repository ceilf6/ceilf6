---
title: 事件循环不空转：Chromium 消息循环源码分析
date: 2026-07-28
summary: 从 MessagePump、SequenceManager 到 RunLoop 三层组件拆解 Chromium 事件循环的实现，重点回答"任务队列为空时线程如何休眠与唤醒"。
source: 工程师沉淀
sourceUrl: https://github.com/ceilf6/Obsidion/tree/main/%E5%B7%A5%E7%A8%8B%E5%B8%88%E6%B2%89%E6%B7%80/%E6%B5%8F%E8%A7%88%E5%99%A8/%E8%BF%9B%E7%A8%8B%E6%A8%A1%E5%9E%8B%EF%BC%88%E4%BA%8B%E4%BB%B6%E5%BE%AA%E7%8E%AF%EF%BC%89/%E4%BA%8B%E4%BB%B6%E5%BE%AA%E7%8E%AF%E6%BA%90%E7%A0%81%203160f8d8d1fd8090b54ee484e98a2ebe.md
---

Chromium 事件循环源码位于 base，由三层核心组件构成，相互协作。

## 一、整体架构层次图

```
┌──────────────────────────────────────────────────────────────┐
│                      RunLoop (用户侧入口)                      │
│              base/run_loop.h / run_loop.cc                    │
└─────────────────────────┬────────────────────────────────────┘
                          │ Delegate::Run()
┌─────────────────────────▼────────────────────────────────────┐
│              ThreadControllerWithMessagePumpImpl              │
│   base/task/sequence_manager/thread_controller_with_...impl  │
│  (实现 RunLoop::Delegate + MessagePump::Delegate)             │
└────────────┬─────────────────────────┬────────────────────────┘
             │ DoWork()                │ SelectNextTask()
┌────────────▼──────────┐  ┌──────────▼──────────────────────┐
│    MessagePump         │  │       SequenceManager           │
│  message_pump.h        │  │  sequence_manager.h             │
│  (平台相关 I/O & 等待)  │  │  (任务队列 & 优先级调度)        │
└────────────────────────┘  │                                  │
                            │  ┌──────────────┐               │
                            │  │  TaskQueue[] │ (多优先级队列) │
                            │  └──────────────┘               │
                            │  ┌──────────────┐               │
                            │  │  WakeUpQueue │ (延迟任务时钟) │
                            │  └──────────────┘               │
                            └─────────────────────────────────┘
```

## 二、MessagePump —— 事件循环核心

**文件**：`base/message_loop/message_pump.h`

`MessagePump` 是抽象基类，定义了循环的骨架：

```cpp
// message_pump.h 中的典型 Run loop 伪代码（注释摘自源码 L193-L215）
for (;;) {
    // 1. 处理原生平台事件（UI消息、I/O完成）
    did_native_work = DoNativeWork();   // 平台相关
    if (should_quit_) break;

    // 2. 处理应用层任务（委托给 Delegate）
    next_work_info = delegate->DoWork();
    if (should_quit_) break;

    // 3. 若有立即任务则继续，否则进入空闲
    if (did_native_work || next_work_info.is_immediate()) continue;

    delegate->DoIdleWork();
    if (should_quit_) break;

    // 4. 等待事件（精确休眠到下一个 delayed_run_time）
    WaitForWork(next_work_info.delayed_run_time);
}
```

**关键设计**：`NextWorkInfo` 结构体（`message_pump.h` L54-L82）的字段含义：

- `delayed_run_time`：下一个延迟任务的触发时间
- `leeway`：允许的时间偏差（用于 CPU 省电对齐唤醒）
- `is_null()` → `is_immediate()`：有立即任务，不休眠
- `is_max()`：无任何任务，无限等待

**具体实现** `message_pump_default.cc`（通用线程版）：

```cpp
void MessagePumpDefault::Run(Delegate* delegate) {
  for (;;) {
    Delegate::NextWorkInfo next_work_info = delegate->DoWork();
    if (!keep_running_) break;

    if (next_work_info.is_immediate()) continue;  // 有任务，不睡

    delegate->DoIdleWork();

    if (next_work_info.delayed_run_time.is_max())
      event_.Wait();                               // 无限等待（WaitableEvent）
    else
      event_.TimedWait(next_work_info.remaining_delay()); // 定时等待
  }
}

void MessagePumpDefault::ScheduleWork() {
  event_.Signal();  // 跨线程唤醒（PostTask 时调用）
}
```

**跨平台 Pump 变体**：

- `message_pump_default.cc` — 通用线程，用 `WaitableEvent` 睡眠
- `message_pump_epoll.cc` — Linux I/O 线程，用 `epoll_wait` 监听 fd
- `message_pump_kqueue.cc` — macOS I/O 线程，用 `kqueue` 监听
- `message_pump_apple.mm` — macOS UI 线程，与 CFRunLoop 集成
- `message_pump_android.cc` — Android UI，基于 Looper/ALooper

## 三、SequenceManager —— 任务调度引擎

**文件**：`base/task/sequence_manager/sequence_manager.h`（同目录有官方 README.md）

SequenceManager 维护多个优先级 `TaskQueue`，并通过 `TaskQueueSelector` 选出下一个要执行的任务。

### 3.1 即时任务的生命周期

```
PostTask()
  → TaskQueueImpl::PostImmediateTaskImpl()
      → 写入 immediate_incoming_queue（支持跨线程锁）
      → 通知 SequenceManager，注册 ReloadEmptyImmediateWorkQueue()
          ↓  （DoWork 开始时批量转移）
      → immediate_work_queue  ← TaskQueueSelector 从这里选取
          ↓
      → 执行 Task
```

**两级队列设计**的原因：`immediate_incoming_queue` 有跨线程写入锁，`immediate_work_queue` 是单线程只读，批量转移可减少锁争用。

### 3.2 延迟任务的生命周期

```
PostDelayedTask(delay)
  → delayed_incoming_queue（按时间排序的优先队列）
  → 更新 TaskQueueImpl::scheduled_wake_up_
  → WakeUpQueue::SetNextWakeUpForQueue()
      → 计算全局最小唤醒时间
      → 传给 ThreadController → MessagePump（设置休眠时长）

当 delayed_run_time 到达：
  WakeUpQueue::MoveReadyDelayedTasksToWorkQueues()
    → 移入 delayed_work_queue
    → 进入常规 TaskQueueSelector 选取流程
```

### 3.3 优先级选择器

**文件**：`task_queue_selector.h`

```cpp
// 核心选取接口
WorkQueue* SelectWorkQueueToService(SelectTaskOption option);
```

- 使用 `WorkQueueSets`（按优先级分组的 WorkQueue 集合）
- 通过 `ActivePriorityTracker`（位掩码）O(1) 找出最高优先级
- 最多支持 `sizeof(size_t) * 8 - 1 = 63` 个优先级

## 四、ThreadControllerWithMessagePumpImpl —— 粘合层

**文件**：`thread_controller_with_message_pump_impl.h`

这是关键的"粘合"类，同时实现三个接口：

- `RunLoop::Delegate` ← 响应 RunLoop 的 Run/Quit
- `MessagePump::Delegate` ← 响应 Pump 的 DoWork/DoIdleWork
- `RunLoop::NestingObserver` ← 监听嵌套循环

```cpp
// DoWork 是 MessagePump 回调的核心
MessagePump::Delegate::NextWorkInfo DoWork() override;
//   内部调用 SequenceManager::SelectNextTask()
//   执行任务
//   返回下一次唤醒时间给 Pump

void ScheduleWork() override;
//   最终调用 MessagePump::ScheduleWork()
//   使用 WorkDeduplicator 避免重复 Signal
```

**WorkDeduplicator**（`work_deduplicator.h`）：通过原子操作确保多次 `PostTask` 只调用一次 `ScheduleWork()`，减少无谓唤醒。

## 五、RunLoop —— 用户侧入口

**文件**：`base/run_loop.h`

`RunLoop` 是开发者直接使用的接口，核心功能：

```cpp
RunLoop run_loop;
DoFooAsyncAndNotify(run_loop.QuitClosure()); // 异步操作完成后退出
run_loop.Run();                              // 阻塞当前线程
```

**嵌套循环两种模式**（`run_loop.h` L56）：

- `Type::kDefault`：嵌套时只处理原生事件（防止应用任务重入）
- `Type::kNestableTasksAllowed`：嵌套时同样执行应用层任务

## 六、省电优化：唤醒对齐（Wake-up Alignment）

`message_pump.h` 中的静态方法管理全局唤醒对齐策略：

```cpp
// 允许在 leeway 范围内合并多个定时器唤醒，减少 CPU 唤醒次数
static void OverrideAlignWakeUpsState(bool enabled, TimeDelta leeway);
static TimeDelta GetLeewayForCurrentThread();
```

```cpp
// AdjustDelayedRunTime 根据 leeway 调整实际唤醒时间
virtual TimeTicks AdjustDelayedRunTime(
    TimeTicks earliest_time,
    TimeTicks run_time,
    TimeTicks latest_time);       // latest = run_time + leeway
```

## 七、完整调用链总结

```
[任意线程] PostTask(task)
    │
    ▼
TaskQueueImpl::immediate_incoming_queue.push(task)
    │
    └─► SequenceManager 通知 → ThreadController::ScheduleWork()
            │
            └─► WorkDeduplicator 去重 → MessagePump::ScheduleWork()
                    │
                    └─► event_.Signal() / epoll_ctl() / ...（平台唤醒）

═══════════════════════════════════════════════

[事件循环线程] MessagePump::Run() 被唤醒
    │
    ▼
delegate->DoWork()  ← ThreadControllerWithMessagePumpImpl
    │
    ├─ immediate: ReloadEmptyImmediateWorkQueue() (批量转移)
    ├─ delayed:   WakeUpQueue::MoveReadyDelayedTasksToWorkQueues()
    │
    ▼
TaskQueueSelector::SelectWorkQueueToService()
    │  (按优先级位掩码 O(1) 选队列)
    ▼
WorkQueue::TakeTaskFromWorkQueue()
    │
    ▼
TaskAnnotator::RunTask(task)    ← 执行任务
    │
    ▼
返回 NextWorkInfo → Pump 决定继续/休眠/定时唤醒
```

## 八、关键设计亮点

- **两级任务队列**（incoming + work）：跨线程 post 用锁写 incoming，主线程批量转移到 work queue，最小化锁竞争
- **WakeUpQueue 集中管理休眠**：所有 TaskQueue 的延迟任务汇聚到 WakeUpQueue，只需一次系统调用设置定时器
- **WorkDeduplicator**：原子状态机防止多次 PostTask 触发多次 ScheduleWork，避免 event_.Signal() 过频
- **leeway 唤醒对齐**：允许将接近的多个唤醒合并，降低功耗（类似 Timer Coalescing）
- **平台无关骨架 + 平台 Pump 替换**：通过 `MessagePump::Create(type)` 工厂方法，UI/IO/Default 三种类型透明切换

## 两种休眠方式

事件循环一直循环，不会导致一直占用资源吗？答案是：任务队列为空时，线程不会空转，而是休眠。决策点在 `message_pump_default.cc`，核心判断条件来自 `DoWork()` 返回的 `NextWorkInfo`：

```cpp
// message_pump_default.cc
if (next_work_info.delayed_run_time.is_max()) {
    event_.Wait();                               // ① 无限期休眠
} else {
    event_.TimedWait(next_work_info.remaining_delay()); // ② 定时休眠
}
```

### ① 无限期休眠 — event_.Wait()

**触发条件**：`delayed_run_time.is_max()` 为 true。

这个值由 `thread_controller_with_message_pump_impl.cc` 设置：

```cpp
// DoWork() 中：
if (!next_wake_up) {              // ← WakeUpQueue 里没有任何延迟任务
    next_work_info.delayed_run_time = TimeTicks::Max();   // 即 is_max() = true
    return next_work_info;
}
```

**含义**：整个 `WakeUpQueue`（最小堆）为空，说明当前没有任何延迟任务等待被调度，线程进入**不定时深度休眠**，直到被显式唤醒。

### ② 定时休眠 — event_.TimedWait(remaining_delay)

**触发条件**：`WakeUpQueue` 中有延迟任务，`DoWork()` 返回了下一个 `WakeUp` 时间。

```cpp
// DoWork() 中：
next_work_info.delayed_run_time =
    CapAtOneDay(next_delayed_do_work, &continuation_lazy_now);  // 最长封顶1天
next_work_info.leeway = GetLeewayForWakeUp(next_wake_up);       // 省电抖动窗口
```

`remaining_delay()` 的计算：

```cpp
// message_pump.h 中 NextWorkInfo
TimeDelta remaining_delay() const {
    return delayed_run_time - recent_now;   // 精确剩余时长
}
```

**含义**：睡到最近一个延迟任务到期，然后自动唤醒。值得注意的是源码中有一个 `CapAtOneDay` 的保护：

```cpp
// thread_controller_with_message_pump_impl.cc L47-L53
// 平台不欢迎 delay > 100,000,000 秒，诊断数据显示
// 99% 的休眠 <= 1秒，> 1小时的休眠总是被更早的事件打断
TimeTicks CapAtOneDay(TimeTicks next_run_time, LazyNow* lazy_now) {
    return std::min(next_run_time, lazy_now->Now() + Days(1));
}
```

## 唤醒机制

唤醒有两条独立的路径。

### 路径一：外部 PostTask 唤醒（跨线程）

```
任意线程 PostTask(task)
    ↓
TaskQueueImpl::PostImmediateTaskImpl()
    ↓
ThreadController::ScheduleWork()    ← [thread_controller...impl.cc L166]
    ↓
WorkDeduplicator::OnWorkRequested() ← 原子操作，防止重复唤醒
    │  返回 kScheduleImmediate（没有挂起的 DoWork 时）
    ↓
pump_->ScheduleWork()               ← [message_pump_default.cc L100]
    ↓
event_.Signal()                     ← WaitableEvent 信号，唤醒 Wait/TimedWait
```

`WorkDeduplicator` 的核心价值：多次 `PostTask` 只触发一次 `Signal()`，避免无效唤醒。源码注释（`work_deduplicator.h` L22）：

```
DoWork 执行期间 OnWorkRequested 的四种时机：
A: 有 pending DoWork → kNotNeeded（不重复 Signal）
B: 在 DoWork 内部  → kNotNeeded
C: 在 WillCheck 之后 → kNotNeeded，但 DidCheck 后会返回 kScheduleImmediate
D: DoWork 结束后   → kScheduleImmediate（需要 Signal）
```

### 路径二：延迟任务到期自动唤醒

```
PostDelayedTask(task, delay)
    ↓
WakeUpQueue::SetNextWakeUpForQueue()  ← 更新最小堆
    ↓
ThreadController::SetNextDelayedDoWork()  ← [impl.cc L199]
    ↓
pump_->ScheduleDelayedWork({run_time, leeway, now})
    ↓
// message_pump_default.cc 中：这个调用实际上什么都不做！
// 因为 Run() 循环自己就会带着正确的 TimedWait 超时时间休眠
// 超时后自然唤醒，不需要额外 Signal
```

`ScheduleDelayedWork` 在 Default Pump 下的注释（`message_pump_default.cc` L104-L110）：

```cpp
void MessagePumpDefault::ScheduleDelayedWork(
    const Delegate::NextWorkInfo& next_work_info) {
  // Since this is always called from the same thread as Run(), there is nothing
  // to do as the loop is already running. It will wait in Run() with the
  // correct timeout when it's out of immediate tasks.
  // 因为总是在 Run() 同一线程调用，循环本身会用正确的超时时间 TimedWait
}
```

## 完整决策流程图

```
DoWork() 执行完毕，返回 NextWorkInfo
           │
           ▼
   is_immediate() ?
   ├─ YES → continue（不休眠，直接下一轮）
   └─ NO
           │
           ▼
   DoIdleWork()
           │
           ▼
   delayed_run_time.is_max() ?
   ├─ YES → event_.Wait()          ← ① 无限期休眠
   │         （WakeUpQueue 为空，等 Signal 唤醒）
   └─ NO  → event_.TimedWait(Δt)  ← ② 定时休眠
             （Δt = delayed_run_time - now，到期自动唤醒）

两种唤醒来源：
  • 外部 PostTask → WorkDeduplicator 判断 → event_.Signal() 强制唤醒
  • 定时休眠超时 → 系统自动唤醒（无需 Signal）
```

## 补充：WaitableEvent 是什么

在 macOS/Linux 上，`WaitableEvent` 底层是 **POSIX `pthread_cond_wait` / `pthread_cond_timedwait`**，线程进入内核态休眠，零 CPU 开销。`Signal()` 对应 `pthread_cond_signal()`，精确唤醒目标线程。

渲染主线程使用的是 message_pump_default（非 UI 线程）或 message_pump_kqueue（macOS I/O 线程），原理相同，只是底层等待系统调用不同。
