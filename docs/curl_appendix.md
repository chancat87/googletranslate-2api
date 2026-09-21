# 真实调用输出附录（curl 实跑，非编造）

> 生成: 2026-09-22 03:31:35 | 命令: scripts/refresh_curl_appendix.ps1 | 基址: http://127.0.0.1:8094

## 非流式翻译
```bash
curl -s -X POST http://127.0.0.1:8094/v1/chat/completions -H 'Content-Type: application/json' -d '{"messages":[{"role":"user","content":"Hello world"}],"target_lang":"zh-CN","stream":false}'
```
```
{"id":"chatcmpl-f8312a4d-f3ce-4f01-acca-d1d71f019dc9","object":"chat.completion","created":1790019097,"model":"google-translate","choices":[{"index":0,"message":{"role":"assistant","content":"你好世界"},"finish_reason":"stop"}],"usage":{"prompt_tokens":2,"completion_tokens":1,"total_tokens":3,"estimate":true}}
```

## 流式翻译
```bash
curl -s -N -X POST http://127.0.0.1:8094/v1/chat/completions -H 'Content-Type: application/json' -d '{"messages":[{"role":"user","content":"Good morning"}],"target_lang":"zh-CN","stream":true}'
```
```
data: {"id": "chatcmpl-bb69738c-edaa-4c39-abab-9ade8d4bff1f", "object": "chat.completion.chunk", "created": 1790019097, "model": "google-translate", "choices": [{"index": 0, "delta": {"content": "\u65e9\u4e0a\u597d"}, "finish_reason": null}]}  data: {"id": "chatcmpl-bb69738c-edaa-4c39-abab-9ade8d4bff1f", "object": "chat.completion.chunk", "created": 1790019097, "model": "google-translate", "choices": [{"index": 0, "delta": {"content": ""}, "finish_reason": "stop"}]}  data: [DONE] 
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
{"status":"ok","service":"googletranslate-2api","version":"1.7.0"}
```
