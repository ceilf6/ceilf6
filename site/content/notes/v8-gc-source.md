---
title: V8 垃圾回收源码分析：Scavenger 与 Mark-Compact
date: 2026-07-28
summary: 从 AllocationType 堆空间划分入手，读 V8 源码看 Minor GC 的 Cheney 复制算法与 Major GC 的三色标记如何分工。
source: 工程师沉淀
sourceUrl: https://github.com/ceilf6/Obsidion/tree/main/%E5%B7%A5%E7%A8%8B%E5%B8%88%E6%B2%89%E6%B7%80/JS/%E5%BA%95%E5%B1%82/%E5%9E%83%E5%9C%BE%E5%9B%9E%E6%94%B6%E4%B8%8E%E5%86%85%E5%AD%98%E6%B3%84%E6%BC%8F%203000f8d8d1fd80e08621cd30a700c26a.md
---

配套实验代码：[github.com/ceilf6/Lab](https://github.com/ceilf6/Lab/commit/f587d8310896b380f6a5d1810087345dc14b7b71)

## 一、堆空间结构

`globals.h` — `AllocationType` 枚举：

```cpp
enum class AllocationType : uint8_t {
  kYoung,    // NEW_SPACE / NEW_LO_SPACE    ← 新生代
  kOld,      // OLD_SPACE / LO_SPACE        ← 老生代
  kCode,     // CODE_SPACE / CODE_LO_SPACE  ← 代码空间
  kMap,      // OLD_SPACE (Map 对象专用)
  kReadOnly, // RO_SPACE                    ← 只读空间（内置对象）
  kTrusted,  // TRUSTED_SPACE               ← 受信任空间
};
```

V8 引擎的**堆内存**会**按对象生命周期分代**为多个空间。

新老生代的区分在于其**内存页标志位**，大多数对象**出生在新生代，在存活过一轮新生代回收之后晋升为老生代**。

## 二、GC 类型选择 — SelectGarbageCollector

`heap.cc`：

```cpp
GarbageCollector Heap::SelectGarbageCollector(AllocationSpace space,
                                              GarbageCollectionReason gc_reason,
                                              const char** reason) const {
  // 1. 请求的是老生代空间 → 必须走 Major GC
  if (space != NEW_SPACE && space != NEW_LO_SPACE) {
    return GarbageCollector::MARK_COMPACTOR;
  }
  // 2. 增量标记已经在运行 → 强制完成 Major GC
  if (incremental_marking()->IsMajorMarking()) {
    return GarbageCollector::MARK_COMPACTOR;
  }
  // 3. 老生代放不下晋升对象 → 升级为 Major GC（防止 Scavenge 失败）
  if (!CanPromoteYoungAndExpandOldGeneration(0)) {
    return GarbageCollector::MARK_COMPACTOR;
  }
  // 4. 默认：新生代用 Minor GC
  return YoungGenerationCollector();  // SCAVENGER 或 MINOR_MARK_SWEEPER
}
```

选择逻辑决定了整个 GC 调用链的下游。

## 三、新生代用 Minor GC — Cheney 复制算法，空间换时间

实验代码：[github.com/ceilf6/Lab](https://github.com/ceilf6/Lab/commit/1b07f1c0e29ce967585c35ddfa143fcc55efd9a3)

Cheney 读作 / ˈtʃeɪni /。

`heap.cc`：

```cpp
void Heap::Scavenge() {
    // 注释直接写明算法名称
    // Implements Cheney's copying algorithm
    scavenger_collector_->CollectGarbage();
}
```

`scavenger.cc` — 核心步骤：

```cpp
void ScavengerCollector::CollectGarbage() {
    SemiSpaceNewSpace* new_space = SemiSpaceNewSpace::From(heap_->new_space());
    new_space->GarbageCollectionPrologue();
    new_space->SwapSemiSpaces();   // ← 关键：From-space 和 To-space 互换
    heap_->new_lo_space()->Flip(); // 大对象空间也翻转
    ...
    // 遍历老生代到新生代的引用（Remembered Set）
    // 遍历根（栈、全局）
    // 每个可达新生代对象：
    //   → 存活次数少 → 复制到 To-space
    //   → 存活次数多 → Promote 晋升到 OLD_SPACE
```

像老生代的三色标记需要标记死对象，而 Cheney 只将在可达图中遍历到的对象设置 forwarding pointer、不需要标记死对象，并且在算法结束后没有该指针的死对象不需要逐个清除，而是直接将 From-space 和 To-space 进行翻转——类似于 React Fiber 双缓冲，都是 **ping-pong 双缓冲模式**：包含垃圾的、旧的 From-space 直接作为下次的 To-space，省得需要向内存申请空间，同时实现了清除。

但是三色标记因为是**原地整理**、不移动的，所以需要标记死状态白色；Cheney 的 forwarding pointer 同时承担了颜色位 + 新地址两个职责。

而由于大部分对象都是老生代，如果老生代也用复制算法双缓冲，那么内存开销太大了——这也是老生代不用复制 GC 的原因。

## 四、老生代用 Major GC

`mark-compact.cc`：

```cpp
void MarkCompactCollector::CollectGarbage() {
    MarkLiveObjects();           // 阶段 1：标记
    ClearNonLiveReferences();   // 阶段 2：清除弱引用/短字符串等
    Sweep();                    // 阶段 3：清扫（回收不可达页）
    Evacuate();                 // 阶段 4：压缩（移动对象，消除碎片）
    Finish();
}
```

### 三色标记

实验代码：[github.com/ceilf6/Lab](https://github.com/ceilf6/Lab/commit/705449071d4b33f52d7f82c57cf90016fb1c5b5e)

从已知活着的根对象出发 DFS，找出所有可达对象，是引用图的遍历：

- 白色（未标记，bit=0）：未被发现或者已确认为垃圾
- 黑色（完全标记，bit=1）：自身及所有子引用均已扫完
- 灰色（bit=1 且仍在 worklist 中）：已发现，但子引用还没扫完

然后白色是垃圾进行清除，黑色的存活（最终不存在灰色，因为从 worklist 出来后自然就是黑色了）。

## 五、总览

```
触发 GC
    ↓
SelectGarbageCollector()
    ├── 新生代分配失败 → Minor GC (Scavenger)
    │       SwapSemiSpaces → 扫根+Remembered Set → 复制存活 → Promote晋升
    │       算法：Cheney's Copying，O(活对象) 时间，无碎片
    │
    └── 老生代压力/增量标记完成 → Major GC (Mark-Compact)
            MarkLiveObjects     三色标记（增量/并发/并行）
            ClearNonLiveReferences  清弱引用
            Sweep               回收不可达页
            Evacuate            移动+压缩，消除碎片

跨代安全保证
    写屏障(WriteBarrier) → 记录 OLD→NEW 引用到 RememberedSet
    → Scavenge 时 RememberedSet 当作额外根，不漏扫
```
