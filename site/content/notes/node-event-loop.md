---
title: Node.js 事件循环：tick 的各个阶段与执行顺序实验
date: 2026-06-05
summary: 用可运行的计时实验梳理 Node.js 事件循环的生命周期：timers、poll、check 各阶段的职责，以及 nextTick/Promise 微任务的插队规则。
source: 工程师沉淀
sourceUrl: https://github.com/ceilf6/Obsidion/tree/main/%E5%B7%A5%E7%A8%8B%E5%B8%88%E6%B2%89%E6%B7%80/NodeJS/Node%E6%A0%B8%E5%BF%83/%E7%94%9F%E5%91%BD%E5%91%A8%E6%9C%9F%20%E4%BA%8B%E4%BB%B6%E5%BE%AA%E7%8E%AF%203320f8d8d1fd8010937ff1f56cd3acaa.md
---

main 启动入口，默认就是 index.js。

接着检查是否要进入事件循环：例如除了 JS 主线程，其他线程是否有要做的事情，还有例如计时器任务。

如果有的话就走一圈然后回来看是否还有要做的，如果仍然有就继续循环、如此往复。

每一次循环都称为一次 tick，过程中有很多阶段，每个阶段都会维护一个自己的事件队列。

## 宏任务

### timers

当前要执行的计时器函数，即到时间的 **setTimeout** 的回调函数。

会从事件队列（排序过的）中一个个把计时器取出来，看当前时间是否超过计时器的节点时间（这个比对是有开销的，这也是为什么 setImmediate 放在 check 阶段）。

### poll

轮询队列。

除了 timers、check 之外，绝大部分回调都会放入该队列，例如文件读取、监听请求。

实验（[Lab commit](https://github.com/ceilf6/Lab/commit/250942bcadd5d955af5961619f329abfc122f7c4)）：

```jsx
const totalStart = Date.now()

setTimeout(function timer1() {
    console.log("timer1", Date.now() - totalStart)
}, 100)

const fs = require("fs")
fs.readFile("NodeJS/sandboxs/testFiles/from.txt", (err, data) => {
    // 从事件循环开始到poll阶段，然后在poll阶段等待回调函数
    // 文件读完之后回调函数在 poll阶段 执行
    console.log("读到文件", Date.now() - totalStart)

    const insideStart = Date.now()
    while (Date.now() - insideStart < 10000) { }
})

/*
读到文件 1
timer1 10007
*/
```

poll 阶段执行其他回调函数可能长时间占用主线程，这也说明了 Node 中计时器回调同样无法保证及时执行。

### check

**setImmediate** 的回调队列。

不和 **setTimeout** 放在一起，就是为了避免**检查（比对计时时间）的开销**：

```jsx
let i = 0
console.time("setTimeout")
function testTimeout() {
    i++
    if (i < 1000) {
        setTimeout(testTimeout, 0)
    } else {
        console.timeEnd("setTimeout")
    }
}
testTimeout()

let i2 = 0
console.time("setImmediate")
function testImmediate() {
    i++
    if (i < 1000) {
        setImmediate(testImmediate)
    } else {
        console.timeEnd("setImmediate")
    }
}
testImmediate()

/*
setImmediate: 14.879ms
setTimeout: 20.22ms
*/
```

两者的顺序问题：

```jsx
setTimeout(() => console.log('setTimeout'), 0)

setImmediate(() => console.log('setImmediate'))
```

注意 setTimeout 的延时最小也是 1ms，所以二者的顺序是不一定的：假如走到 timers 阶段时已经过了 1ms，那么就先执行 setTimeout；否则本轮在 check 阶段执行 setImmediate，等到第二圈的时候再执行 setTimeout。

> setTimeout() 等价于 setTimeout( , 0)

```jsx
const fs = require("fs");
fs.readFile("./index.js", () => {
  setTimeout(() => console.log(1));
  setImmediate(() => console.log(2));
});
```

由于回调本身已经是在 poll 阶段之后才触发，所以接下来一定先到 check 阶段——肯定是先 setImmediate。

## 微任务

上面说的都是事件循环队列中的宏任务。微任务不在事件循环队列里面，它表示希望以最快速度执行的任务。

**事件循环中，每次执行一个阶段的回调之前，必须要先清空 nextTick 和 promise 队列。**

- nextTick：优先级最高
- Promise：在 nextTick 之后

```jsx
setImmediate(() => console.log('Immediate'))

process.nextTick(() => {
    console.log('nextTick')
    process.nextTick(() => console.log('nextTick => nextTick'))
})

console.log('同步代码')

Promise.resolve().then(() => {
    console.log('pro')
    Promise.reject().catch(() => console.log('pro => pro'))
    process.nextTick(() => console.log('pro => nextTick'))
})

/*
同步代码
nextTick
nextTick => nextTick
pro
pro => pro
pro => nextTick
Immediate
*/
```

综合练习：

```jsx
/*
nextTicks: 

promises:

timers: timeout0, timeout3

checks: immediate
*/
async function async1() {
  console.log("async1 start");
  await async2();
  console.log("async1 end");
}
async function async2() {
  console.log("async2");
}
console.log("script start");
setTimeout(function () {
  console.log("setTimeout0");
}, 0);
setTimeout(function () {
  console.log("setTimeout3");
}, 3);
setImmediate(() => console.log("setImmediate"));
process.nextTick(() => console.log("nextTick"));
async1();
new Promise(function (resolve) {
  console.log("promise1");
  resolve();
  console.log("promise2");
}).then(function () {
  console.log("promise3");
});
console.log("script end");

/*
script start
async1 start
async2
promise1
promise2
script end
nextTick
async1 end
promise3
setTimeout0
setImmediate
setTimeout3
*/
```
