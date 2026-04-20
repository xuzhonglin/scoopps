# ScoopPS

个人 [Scoop](https://scoop.sh) 应用仓库，收录一些常用 Windows 软件的 Scoop 清单。

## 已收录应用

| 应用 | 说明 |
|------|------|
| [微信](bucket/weixin.json) | 微信 QT 多桌面端统一版，支持数据持久化 |

## 安装使用

```pwsh
# 添加本仓库
scoop bucket add scoopps https://github.com/xuzhonglin/scoopps

# 安装应用
scoop install scoopps/weixin
```

## 参考来源与致谢

本仓库的部分清单灵感与实现参考了以下项目：

- [**软件狗狗 (sdoog)**](https://github.com/xrgzs/sdoog) — 一个对现有 Scoop 仓库的补充项目，采用激进的持久化策略，充分利用 Scoop 的软链接特性持久化程序配置，重装系统后无需重新配置。感谢 [@xrgzs](https://github.com/xrgzs) 的工作！

## 贡献

欢迎提交 PR 添加新的应用清单。请参考 [Scoop App Manifests](https://github.com/ScoopInstaller/Scoop/wiki/App-Manifests) 编写清单文件。
