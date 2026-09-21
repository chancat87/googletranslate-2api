# Web UI 前端改造方案 (v2.5.0)

## 1. Executive Summary

目标人群是部署者 + 日常用户：既要看得懂服务健康，也要能直接翻译。方案采用
**无构建的静态 SPA**（FastAPI 直接托管单个 HTML，CSS/JS 内联，零外部依赖），
保留现有 `/admin` 管理语义并新增 `/app` 入口，把“翻译工作台 + 运维面板”合并成一个
响应式界面。收益：部署面不变、离线可看、无 Node 构建链、CI/E2E 简单；取舍是
不引入 React/Vue 生态的组件化工具链，用原生渲染函数 + 设计 token 达到同等一致性。

## 2. Responsive Strategy

- 断点（mobile-first）：`0-639px` 手机、`640-1023px` 平板、`1024-1439px` 桌面、`1440px+` 大屏。
- 布局：手机用顶部品牌栏 + 底部导航；平板用横向可滚动导航；桌面及以上固定侧边栏（240px）。
- 单位：布局用 `clamp()` 控制容器宽度但不缩放字号；`min-height:100dvh` 适配动态视口；
  `env(safe-area-inset-*)` 处理刘海屏；触控目标 ≥44px；hover 仅增强，不承载唯一入口。
- 字号：正文 14px，指标卡数值 24px，标题 18px；不随视口宽度缩放，保证窄屏可读。

## 3. Performance Blueprint

- 目标：LCP <2.5s、INP <100ms、CLS <0.1、交互动画 60fps。
- 手段：单文件无外部请求，CSS 动画只改 `transform/opacity`，`content-visibility` 用于长表，
  翻译流式用 fetch ReadableStream 逐行渲染，不用重复全量 innerHTML。
- 降级：无 Service Worker（静态单文件收益低，不引入缓存复杂性）；断网时给出明确错误态。

## 4. Design System Specification

- Token：颜色/间距/圆角/阴影/字体全部走 CSS 变量；8px 间距基准（4/8/12/16/24/32/48）。
- 配色：浅色为暖白 + 墨黑 + 蓝青双强调色（蓝 `#0f62fe`、青 `#0e9384`），避免单一色相；
  深色为低饱和石墨 + 高对比文字；成功/警告/错误语义色各有独立 token。
- 圆角：按钮 6px、卡片 8px、胶囊标签 999px；阴影分 3 档，卡片默认 1 档。
- 动效：切换 160-240ms ease-out；`prefers-reduced-motion` 下关闭位移动画。

## 5. UX/UI Pattern Library Plan

- 导航：总览 / 翻译 / Keys / 用量 / 最近请求，桌面侧栏、移动底部导航；面包屑简化为“模块标题 + 状态点”。
- 反馈：加载骨架、toast、按钮 loading 态、空态文案、错误内联提示。
- 可访问性：语义化 landmark、表单 label、`aria-live` 结果区、`role="status"` toast、
  键盘 focus-visible 环、对比度满足 WCAG 2.1 AA。

## 6. Technical Architecture

- 栈：FastAPI 静态路由 + 原生 HTML/CSS/JS；不做构建；`app/web/app.html` 单文件。
- 结构：`main.py` 暴露 `/app`（新 UI）与 `/admin`（兼容入口，同一文件）；
  旧 `admin.html` 移除，避免双实现漂移。
- 主题：`data-theme="light|dark"` + localStorage；CSS 变量在 `:root` 与 dark 覆盖。
- 数据：token 存 localStorage；所有调用走同源 API；翻译流式解析 SSE。

## 7. Phased Rollout Plan

- MVP：翻译工作台 + 总览（可用、可翻译、可看健康）。
- 补齐：Keys / 用量 / 最近请求 / 自检。
- 打磨：主题、移动导航、toast、空态、键盘与读屏支持。
- 收口：单元/E2E/CI 全绿后再发版。

## 8. Quality Checklist

- 320 / 768 / 1024 / 1440 宽度无溢出、无横向滚动。
- 深色与浅色下文字对比度均达标，焦点可见。
- `/app` 与 `/admin` 均返回 HTML 且包含“管理面板”。
- 翻译流式/非流式均有真实 E2E 通过；无外部依赖请求。
