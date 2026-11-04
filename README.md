# 战双库街区自动签到

[English](README.en.md)

通过 Docker Compose 定时领取战双每日补给，并完成库街区签到、浏览、点赞和分享任务。支持多账号，补给奖励发往绑定角色的游戏邮箱。

## 使用

需要 Docker 和 Docker Compose，并已在库街区 App 绑定战双角色。

1. 登录[库街区网页](https://www.kurobbs.com/pns/home/)，按 F12 打开「网络」，刷新页面，从发往 `api.kurobbs.com` 的已登录请求头中复制 `token`。
2. 将 `config/accounts.example.json` 复制为 `config/accounts.json`，填入 Token：

   ```json
   [
     {"name": "账号1", "token": "你的Token", "source": "h5", "enabled": true}
   ]
   ```

   多账号继续添加对象，名称不要重复。Token 失效后重新获取并替换；请勿公开账号配置。

3. 在项目目录启动并查看日志：

   ```sh
   docker compose up -d --build
   docker compose logs -f --tail=100
   ```

默认启动时执行一次，之后每天北京时间 **09:30** 执行；已完成的任务自动跳过。

## 调整时间

将 `.env.example` 复制为 `.env`，按需修改：

```dotenv
TZ=Asia/Shanghai
SIGN_TIME=09:30
RUN_ON_START=true
```

`SIGN_TIME` 为每日执行时间；`RUN_ON_START=false` 可关闭启动时执行。修改后运行 `docker compose up -d`。

停止服务：`docker compose down`。

## 失败邮件（可选）

在 QQ 邮箱设置中开启 IMAP/SMTP 服务并生成授权码。将 `config/mail.example.json` 复制为 `config/mail.json`，设置 `enabled: true`，填写发件邮箱、授权码和收件邮箱（可以是自己）。使用 QQ 邮箱加密 SMTP，无需搭建邮件服务器。

更新镜像后发送测试邮件，不会执行签到：

```sh
docker compose build
docker compose run --rm pgr-sign python app.py --test-email
docker compose up -d
```

每轮仅汇总最终失败，成功不通知。邮件不包含 Token 或角色信息；授权码不要公开。修改邮件配置后下一轮生效，设置 `enabled: false` 可关闭。

> 从 App 获取 Token 时，`source` 应与原请求头一致，填写 `ios` 或 `android`。若日志提示配置文件无法读取，请检查文件权限，容器用户 UID 为 `10001`。

[GPL-3.0 许可证](LICENSE)
