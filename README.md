# 库街区定时任务

[English](README.en.md)

使用 Docker Compose 每天完成库街区战双社区的签到、浏览 3 篇帖子、点赞 5 次、分享任务，并查询金币。已完成的任务会跳过，执行后以服务端任务状态确认结果。支持多个账号，逐个执行。

同时执行战双 **每日补给** 签到，奖励由库街区发往绑定角色的游戏邮箱。请先在库街区 App 绑定战双角色；程序通过 Token 自动获取角色和服务器，为所有已绑定的战双角色签到，无需手填角色 ID。今日已签到会跳过，不执行补签。每日补给与社区任务分别确认结果，一项失败不阻止另一项。

## 配置账号

1. 在[库街区官网](https://www.kurobbs.com/pns/home/)手动登录。
2. 打开浏览器开发者工具的 Network（网络）面板，刷新页面，在发往 `api.kurobbs.com` 的已登录请求头中复制 `token`。如果已有可用 Token，直接使用。
3. 将 `config/accounts.example.json` 复制为 `config/accounts.json`，替换 Token：

```json
[
  {"name": "账号1", "token": "你的Token", "enabled": true}
]
```

多个账号添加多个对象，名称保持唯一。可选填写请求头中的 `devcode` 和 `distinct_id`；未填写时按账号名称生成稳定标识。Token 失效后需手动重新获取，程序不会自动登录或禁用账号。更新账号文件后，下一轮自动读取。

`source` 默认是 `h5`，对应上述浏览器取 Token 的方式。若从 App 获取 Token，请将该账号的 `source` 设置为原请求头中的 `ios` 或 `android`。Token 和来源需要匹配，来源不匹配也可能被服务端返回“登录已过期”。

Token 保存在本地配置中，只读挂载到容器；不要分享该文件或截图。配置文件已排除在 Git 和镜像构建之外。在 Linux 上需保证容器用户 UID `10001` 能读取账号文件，例如将其所有者设为 `10001:10001` 并设置文件权限 `600`；配置目录需允许该用户进入。

## Docker Compose 部署

在项目根目录执行，需要 Docker Engine 和 Compose v2：

```sh
docker compose build
docker compose run --rm pgr-sign python app.py --check
docker compose up -d
docker compose logs -f --tail=100
```

`--check` 只检查账号和定时配置，不联网验证 Token。默认启动时执行一次，之后每天北京时间 **09:30** 执行。失败写入容器日志，不发送通知。

需要修改时间时，将 `.env.example` 复制为 `.env`：

```dotenv
TZ=Asia/Shanghai
SIGN_TIME=09:30
RUN_ON_START=true
```

`SIGN_TIME` 使用 24 小时制 `HH:MM`；`TZ` 使用 IANA 时区名称。`RUN_ON_START=false` 表示启动后只等待下一个定时时刻，不补跑停机期间的任务。修改 `.env` 后执行 `docker compose up -d`。

停止服务：

```sh
docker compose down
```

手动执行一轮时，先停掉定时服务，避免重复执行：

```sh
docker compose stop pgr-sign
docker compose run --rm pgr-sign python app.py --once
docker compose up -d
```

网络或任务未完成时，每个账号最多尝试 3 次，间隔 10 秒；认证失败不重试。一次执行最终失败返回非零退出码。认证失败日志会显示接口和业务码，请先核对 Token 与 `source` 是否匹配，再确认是否需要重新登录；其他失败可按上述方式重跑。不要同时启动多个实例使用同一账号。

## 数据访问

运行时仅请求 `https://api.kurobbs.com` 的社区、用户绑定信息和战双每日补给接口，禁止 HTTP 重定向，不使用环境代理，保持 TLS 证书验证。日志不输出 Token、请求头或接口响应原文。容器以非 root 用户运行，不开放端口，文件系统及账号挂载只读。

## 许可

基于 Kuro-autosignin 整理，保留原项目的 [GPL-3.0 许可证](LICENSE)。
