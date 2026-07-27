---
title: 浏览器如何决定携带哪些 Cookie：Chromium 源码分析
date: 2026-06-15
summary: 沿 URLRequest 到 CookieMonster 的调用链，逐层拆解 Chromium 决定一次请求携带哪些 Cookie 的完整决策管线。
source: 工程师沉淀
sourceUrl: https://github.com/ceilf6/Obsidion/tree/main/%E5%B7%A5%E7%A8%8B%E5%B8%88%E6%B2%89%E6%B7%80/%E7%BD%91%E7%BB%9C/cookie/%E6%B5%8F%E8%A7%88%E5%99%A8%E5%86%B3%E5%AE%9A%E6%90%BA%E5%B8%A6cookie%E8%BF%87%E7%A8%8B/chromium%E6%BA%90%E7%A0%81%E5%88%86%E6%9E%90%203170f8d8d1fd80178319ce2d35aeff44.md
---

浏览器决定一次请求携带哪些 Cookie，整个决策链涉及 4 个核心文件，按调用顺序展开。

## 一、总体调用链

```
URLRequest 发起 HTTP 请求
    ↓
URLRequestHttpJob::OnGotFirstPartySetMetadata()   [url_request_http_job.cc L554]
    ↓ ShouldAddCookieHeader() 通过
URLRequestHttpJob::AddCookieHeaderAndStart()       [L820]
    ├─ 计算 SameSite 上下文
    └─ CookieMonster::GetCookieListWithOptionsAsync() 异步查询
            ↓
       CookieMonster::GetCookieListWithOptions()    [cookie_monster.cc L764]
            ├─ FindCookiesForRegistryControlledHost() — 按域快速索引
            └─ FilterCookiesWithOptions()            [L1332]
                    ↓
               对每个候选 cookie 调用:
               CookieBase::IncludeForRequestURL()   [cookie_base.cc L218]
               ← 通过七道检查，确定 include/exclude 及原因
            ↓
URLRequestHttpJob::SetCookieHeaderAndStart()        [L854]
    ├─ PrivacyMode 终极检查
    ├─ AnnotateAndMoveUserBlockedCookies() — 委托用户设置
    └─ 拼接 Cookie 请求头
```

## 二、第一步：是否应该附带 Cookie — ShouldAddCookieHeader()

**文件**：`net/url_request/url_request_http_job.cc` L2096

```cpp
bool URLRequestHttpJob::ShouldAddCookieHeader() const {
  // 必须同时满足两个条件：
  // 1. URLRequestContext 有可用的 CookieStore
  // 2. 请求允许携带凭据 (allow_credentials)
  return request_->context()->cookie_store() && request_->allow_credentials();
}
```

`allow_credentials()` 对应 fetch 的 `credentials: 'include'/'same-origin'`，若为 `omit` 则直接跳过所有 cookie 逻辑。

## 三、第二步：计算 SameSite 请求上下文 — ComputeSameSiteContextForRequest()

**文件**：`net/url_request/url_request_http_job.cc` L838，实现位于 `net/cookies/cookie_util.cc` L895

```cpp
// url_request_http_job.cc AddCookieHeaderAndStart() 内
CookieOptions::SameSiteCookieContext same_site_context =
    cookie_util::ComputeSameSiteContextForRequest(
        request_->method(),          // HTTP 方法（GET/POST/...）
        request_->url_chain(),       // 请求 URL 链（含重定向历史）
        request_->site_for_cookies(),// 顶级框架站点
        request_->initiator(),       // 请求发起方 Origin
        is_main_frame_navigation,    // 是否主框架导航
        force_ignore_site_for_cookies,
        request_->ignore_unsafe_method_for_same_site_lax());
```

`ComputeSameSiteContextForRequest` 的核心逻辑（`cookie_util.cc` L895）按 RFC6265bis 规范计算上下文等级：

- `SAME_SITE_STRICT`：URL、initiator、site_for_cookies 三者注册域相同
- `SAME_SITE_LAX`：URL 与 site_for_cookies 注册域相同 + 主框架导航 + 安全方法（GET/HEAD）
- `SAME_SITE_LAX_METHOD_UNSAFE`：同上但方法不安全（POST 等）
- `CROSS_SITE`：其他情况

同时会计算两套：`schemeless`（忽略 http/https 差异）和 `schemeful`（区分协议），最终合并为一个 `SameSiteCookieContext`。

## 四、第三步：候选 Cookie 查找 — GetCookieListWithOptions()

**文件**：`net/cookies/cookie_monster.cc` L764

```cpp
void CookieMonster::GetCookieListWithOptions(...) {
  // 1. URI scheme 白名单检查（只处理 http/https/ws/wss 等）
  if (HasCookieableScheme(url)) {
    // 2. 按注册域（eTLD+1）快速索引候选 cookie
    //    内部使用 std::map，key 是 domain，O(log n)
    std::vector<CanonicalCookie*> cookie_ptrs =
        FindCookiesForRegistryControlledHost(url);

    // 3. 同时查询 Partitioned Cookie（CHIPS 机制）
    for (const CookiePartitionKey& key : cookie_partition_key_collection) {
        auto partitioned = FindPartitionedCookiesForRegistryControlledHost(key, url);
        cookie_ptrs.insert(...);
    }

    // 4. 排序（保证 path 越长越靠前，创建时间越早越靠前）
    std::sort(cookie_ptrs.begin(), cookie_ptrs.end(), CookieSorter);

    // 5. 逐个过滤
    FilterCookiesWithOptions(url, options, ..., cookie_ptrs,
                             included_cookies, excluded_cookies);
  }
}
```

## 五、第四步（核心）：逐个 Cookie 访问决策 — CookieBase::IncludeForRequestURL()

**文件**：`net/cookies/cookie_base.cc` L218

这是整个决策的最核心函数，对每个候选 cookie 执行**七层检查**，任意一层失败都会在 `CookieInclusionStatus` 中添加排除原因。

### 检查 1：HttpOnly 过滤

```cpp
// 若 options 要求排除 HttpOnly（如 JS document.cookie 访问），则排除
if (options.exclude_httponly() && IsHttpOnly()) {
    status.AddExclusionReason(EXCLUDE_HTTP_ONLY);
}
```

HTTP 请求的 options 默认 `include_httponly()`，因此 HTTP 请求**不会**因此排除 HttpOnly cookie。

### 检查 2：Secure 属性 × URL 协议

```cpp
switch (cookie_access_scheme) {
    case kNonCryptographic:  // http://
        if (SecureAttribute()) {
            status.AddExclusionReason(EXCLUDE_SECURE_ONLY);
            // Secure cookie 不能发送到 http:// 请求
        }
        break;
    case kCryptographic:     // https://
    case kTrustworthy:       // localhost 等被信任的非 https 源
        is_allowed_to_access_secure_cookies = true;
        break;
}
```

### 检查 3：Scheme 绑定（kSchemeBoundCookies Feature）

```cpp
// 若 cookie 设置时是 https，不允许 http 请求读取（新特性）
if (source_scheme_ == CookieSourceScheme::kSecure &&
    cookie_access_scheme == CookieAccessScheme::kNonCryptographic) {
    if (IsSchemeBoundCookiesEnabled())
        status.AddExclusionReason(EXCLUDE_SCHEME_MISMATCH);
    else
        status.AddWarningReason(WARN_SCHEME_MISMATCH);
}
```

### 检查 4：Port 绑定（kPortBoundCookies Feature）

```cpp
bool port_matches = url_port == source_port_
                 || source_port_ == PORT_UNSPECIFIED
                 || IsDomainCookie();  // domain 级 cookie 不绑端口
if (!port_matches && !trustworthy_and_443) {
    if (IsPortBoundCookiesEnabled())
        status.AddExclusionReason(EXCLUDE_PORT_MISMATCH);
    else
        status.AddWarningReason(WARN_PORT_MISMATCH);
}
```

### 检查 5：Domain 匹配 — IsDomainMatch()

**文件**：`net/cookies/cookie_util.cc` L704

```cpp
bool IsDomainMatch(domain, host) {
    // 精确匹配（host cookie：domain 不含前缀 "."）
    if (host == domain) return true;

    // domain cookie（domain 以 "." 开头）
    // e.g. domain=".example.com"，host="sub.example.com" → 匹配
    if (domain[0] != '.') return false;
    if (domain.compare(1, npos, host) == 0) return true;  // ".example.com" == "example.com"

    // 后缀匹配：host 末尾包含 domain
    return host.length() > domain.length() &&
           host.ends_with(domain);  // "sub.example.com" ends with ".example.com"
}
```

域名匹配规则图示：

```
Cookie domain=".example.com"
  ✓ example.com
  ✓ sub.example.com
  ✓ a.b.example.com
  ✗ notexample.com
  ✗ evil.com

Cookie domain="sub.example.com"（host cookie，无前缀点）
  ✓ sub.example.com（精确匹配）
  ✗ example.com
  ✗ other.example.com
```

### 检查 6：Path 匹配 — IsOnPath()

**文件**：`net/cookies/cookie_util.cc` L737

```cpp
bool IsOnPath(cookie_path, url_path) {
    // url_path 必须以 cookie_path 为前缀
    if (!url_path.starts_with(cookie_path)) return false;

    // 防止 /blah 错误匹配 /blahblah/
    // cookie_path 末尾是 '/'，或 url_path 中 cookie_path 后紧接 '/'
    if (cookie_path.length() != url_path.length()
        && cookie_path.back() != '/'
        && url_path[cookie_path.length()] != '/') {
        return false;
    }
    return true;
}
```

路径匹配示例：

```
Cookie path="/admin"
  ✓ /admin
  ✓ /admin/
  ✓ /admin/users
  ✗ /adminpanel     ← 关键：/ 边界检查阻止此误匹配

Cookie path="/"
  ✓ 任何路径
```

### 检查 7：SameSite 属性检查

```cpp
CookieEffectiveSameSite effective_same_site = GetEffectiveSameSite(access_semantics);

switch (effective_same_site) {
    case STRICT_MODE:
        // 请求上下文必须达到 SAME_SITE_STRICT
        if (context < SAME_SITE_STRICT)
            status.AddExclusionReason(EXCLUDE_SAMESITE_STRICT);
        break;

    case LAX_MODE:
        // 请求上下文必须达到 SAME_SITE_LAX
        if (context < SAME_SITE_LAX)
            status.AddExclusionReason(EXCLUDE_SAMESITE_LAX);
        break;

    case NO_RESTRICTION:  // SameSite=None
        // 还要检查必须有 Secure 属性，否则拒绝
        if (SameSite() == NO_RESTRICTION && !SecureAttribute())
            status.AddExclusionReason(EXCLUDE_SAMESITE_NONE_INSECURE);
        break;
}
```

`SameSite` 未设置时（`UNSPECIFIED`）默认等同于 `LAX_MODE_ALLOW_UNSAFE`，宽限期内允许 POST 等主框架导航携带。

## 六、第五步：用户隐私设置过滤 — SetCookieHeaderAndStart()

**文件**：`net/url_request/url_request_http_job.cc` L854

即使 `IncludeForRequestURL` 通过，还有最后两道检查：

```cpp
// 检查 PrivacyMode（隐私浏览模式）
if (ShouldBlockAllCookies(request_info_.privacy_mode)) {
    // PRIVACY_MODE_ENABLED: 隐身模式或用户全局禁用
    // → 把所有 cookie 移入 excluded_cookies，标记 EXCLUDE_USER_PREFERENCES
    excluded_cookies.insert(...all maybe_included_cookies...);
    maybe_included_cookies.clear();
} else {
    // 咨询 CookieAccessDelegate（浏览器层面的用户设置）
    // 例如：用户在 Chrome 设置里屏蔽了某个站点的 Cookie
    AnnotateAndMoveUserBlockedCookies(maybe_included_cookies, excluded_cookies);
}
```

最终通过的 cookie 才会被拼接进请求头：

```cpp
std::string cookie_line = CanonicalCookie::BuildCookieLine(maybe_included_cookies);
request_info_.extra_headers.SetHeader(HttpRequestHeaders::kCookie, cookie_line);
```

## 七、完整决策逻辑总结

```
对每个候选 Cookie，顺序执行以下检查，任一失败即排除：

┌─ ① ShouldAddCookieHeader？        allow_credentials && cookie_store 存在
├─ ② URI Scheme 白名单              http/https/ws/wss 等
│
│  ── CookieBase::IncludeForRequestURL() ──
├─ ③ HttpOnly 过滤                  JS 调用时排除，HTTP 请求不排除
├─ ④ Secure 属性 × 协议             http:// 不能发送 Secure cookie
├─ ⑤ SchemeBound（新特性）         source_scheme 需与请求协议匹配
├─ ⑥ PortBound（新特性）           source_port 需与请求端口匹配
├─ ⑦ Domain 匹配                   host cookie 精确匹配，domain cookie 后缀匹配
├─ ⑧ Path 匹配                     url_path 必须以 cookie_path 为前缀（边界精确）
├─ ⑨ SameSite 检查                 None/Lax/Strict × 请求的同站上下文等级
│     SameSite=None 还要求有 Secure 属性
│
├─ ⑩ PrivacyMode 检查              隐身模式 / PRIVACY_MODE_ENABLED → 全部阻止
└─ ⑪ CookieAccessDelegate          用户在浏览器设置里对特定站点的屏蔽
```
