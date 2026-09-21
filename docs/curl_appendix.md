# 真实调用输出附录（curl 实跑，非编造）

> 生成: 2026-09-22 04:30:27 | 命令: scripts/refresh_curl_appendix.ps1 | 基址: http://127.0.0.1:8094

## 非流式翻译
```bash
curl -s -X POST http://127.0.0.1:8094/v1/chat/completions -H 'Content-Type: application/json' -d '{"messages":[{"role":"user","content":"Hello world"}],"target_lang":"zh-CN","stream":false}'
```
```
{"id":"chatcmpl-224c3f54-d10b-4802-98bb-bcd72e6866e5","object":"chat.completion","created":1790022629,"model":"google-translate","choices":[{"index":0,"message":{"role":"assistant","content":"你好世界"},"finish_reason":"stop"}],"usage":{"prompt_tokens":2,"completion_tokens":1,"total_tokens":3,"estimate":true}}
```

## 流式翻译
```bash
curl -s -N -X POST http://127.0.0.1:8094/v1/chat/completions -H 'Content-Type: application/json' -d '{"messages":[{"role":"user","content":"Good morning"}],"target_lang":"zh-CN","stream":true}'
```
```
data: {"id": "chatcmpl-ece0e03b-3f4a-4e62-89a6-06d2179773c3", "object": "chat.completion.chunk", "created": 1790022629, "model": "google-translate", "choices": [{"index": 0, "delta": {"content": "\u65e9\u4e0a\u597d"}, "finish_reason": null}]}  data: {"id": "chatcmpl-ece0e03b-3f4a-4e62-89a6-06d2179773c3", "object": "chat.completion.chunk", "created": 1790022629, "model": "google-translate", "choices": [{"index": 0, "delta": {"content": ""}, "finish_reason": "stop"}]}  data: [DONE] 
```

## 批量翻译
```bash
curl -s -X POST http://127.0.0.1:8094/v1/translate/batch -H 'Content-Type: application/json' -d '{"texts":["apple","banana"],"target_lang":"zh-CN"}'
```
```
{"object":"list","data":[{"text":"apple","translated":"苹果","ok":true,"error":null},{"text":"banana","translated":"香蕉","ok":true,"error":null}],"count":2}
```

## 语言检测
```bash
curl -s -X POST http://127.0.0.1:8094/v1/translate/detect -H 'Content-Type: application/json' -d '{"text":"hello world"}'
```
```
{"object":"language_detection","scripts":[],"target_lang":"zh-CN","source":"script_heuristic","note":"基于字符集的轻量推断, 非 Google 官方语言检测"}
```

## health
```bash
curl -s http://127.0.0.1:8094/health
```
```
{"status":"ok","service":"googletranslate-2api","version":"2.6.0"}
```
