# 港华燃气 Home Assistant 集成（资源优化版）

本项目复刻自 [linyf0766/towngas-ha](https://github.com/linyf0766/towngas-ha)，
用于在 Home Assistant 中读取港华燃气余额。

## 本版改进

- 每次更新先使用轻量 HTTP 请求，仅在遇到防爬页面时调用 FlareSolverr；
- FlareSolverr 使用无会话请求，请求完成后自动关闭临时 Chromium；
- 不再长期保存随机浏览器会话，避免 Home Assistant 重载后遗留进程；
- 使用 Home Assistant 共享的 `aiohttp` 会话，减少连接和对象开销；
- 显式关联 `ConfigEntry`，兼容 Home Assistant 2026.8 之后的协调器要求；
- 使用 `CoordinatorEntity` 和 `async_config_entry_first_refresh`；
- 更新间隔限制为 5～1440 分钟，避免误设成高频请求；
- 增加“立即更新余额”按钮，可随时手动刷新且不改变定时更新间隔；
- 不再在 INFO 日志中输出用户号和燃气余额；
- 增加 JSON、HTML `<pre>`、JSONP、直连及防爬回退测试。

## 安装

### HACS 自定义仓库

1. 打开 HACS；
2. 添加自定义仓库 `https://github.com/wpf382301/towngas-ha`；
3. 类型选择“集成”；
4. 安装“港华燃气”并重启 Home Assistant。

### 手动安装

将 `custom_components/towngas` 复制到 Home Assistant 的
`/config/custom_components/towngas`，然后重启 Home Assistant。

## 配置

在 Home Assistant 中添加“港华燃气”，选择燃气公司并填写：

- `subsCode`：用户号；
- `updatetime`：更新间隔，单位为分钟；
- `flaresolverr_url`：默认 `http://127.0.0.1:8191/v1`。

默认更新间隔为 30 分钟。若数据变化不频繁，建议设置为 480 分钟。

集成会在同一设备下创建“立即更新余额”按钮。点击后会马上执行一次余额
查询；若直连遇到防爬，仍只为本次查询临时调用 FlareSolverr。

## FlareSolverr

只有存在防爬的地区才需要 FlareSolverr。建议仅监听本机：

```yaml
ports:
  - "127.0.0.1:8191:8191"
```

本集成不会创建永久会话。每次需要浏览器时发送一次 sessionless
`request.get`，FlareSolverr 会在返回结果后销毁临时浏览器，因此空闲时不会
长期保留港华燃气专用的 Chromium 进程。

## 获取用户号

打开 [港华燃气网上营业厅](https://www.towngasvcc.com/)，选择所属燃气公司，
登录后进入“业务办理 → 账单缴费”。地址中的用户编号即为 `subsCode`。

## 测试

在包含 Home Assistant Python 环境的容器中执行：

```sh
python -m unittest discover -s tests -v
```

## 回退

替换现有插件前请备份 `/config/custom_components/towngas`。如果升级后出现问题，
恢复该目录并重启 Home Assistant 即可。
