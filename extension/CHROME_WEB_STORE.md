# Chrome 商店发布

## 首次提交

1. 用你选定的 Google 账号打开 [Chrome 商店开发者后台](https://chrome.google.com/webstore/devconsole/)。若尚未注册，阅读开发者条款、支付一次性注册费，验证联系邮箱，并启用 Google 两步验证。请在自己的浏览器完成这些步骤。
2. 新建项目并上传 `sjtu-tennis-extension-1.0.7-chrome-web-store.zip`。商店资料填写下方文案，并上传图标和截图。若拿到的是提交资料合集，先解压合集，再上传里面的扩展 ZIP。仓库本地生成的扩展 ZIP 在 `dist/`，图片在 `dist/chrome-web-store/`。申请审核前在 **分发 → 可见性** 选择 **Public（公开）**，保持免费。
3. 提交审核。审核通过并发布后，在 Windows 和 Mac 用 Chrome 打开该项目的商店链接安装。原来加载了开发版的 Chrome，先停止任务、记下配置并停用开发版，再使用商店版。

官方说明：[开发者注册](https://developer.chrome.com/docs/webstore/register) · [分发设置](https://developer.chrome.com/docs/webstore/cws-dashboard-distribution) · [提交审核](https://developer.chrome.com/docs/webstore/publish)

## 商店详情

- 名称：网球预约助手（由 ZIP 的清单提供）
- 语言：中文（简体）；分类：工具（Tools）；价格：免费
- 图标：`icon-128.png`；截图：`01-monitor.png`、`02-scheduled-booking.png`；小型宣传图：`promo-440x280.png`（后台有该字段时使用）
- 隐私政策链接：<https://github.com/VonSkylar/sjtu_tennis_toolkit/blob/main/extension/PRIVACY.md>
- 支持链接：<https://github.com/VonSkylar/sjtu_tennis_toolkit/issues>

详细说明：

> 网球预约助手在 Chrome 侧边栏监控上海交通大学体育场馆预约网站的东区和胡晓明网球场，并可按你的设置提交预约。适用于 Windows 和 Mac 的桌面 Chrome。
>
> 空场监控：按场馆、日期、时段和场地范围检查空场，发现空场时发送本机通知并播放提示音。只想接收提醒时，请先关闭默认开启的「唯一空场自动下单」。开启时，一轮只有一个符合条件的场次才会自动提交；多个场次只提醒。
>
> 定时抢场：选择放场时间、优先时段与场地后启动。到时间后，扩展会通过学校网页自动尝试提交预约，明确成功后不再提交其他场次。
>
> 你需要在学校网页正常登录并自行处理验证码。使用自动预约前，请先查看学校预约规则及须知；扩展可根据所选任务勾选须知并提交订单。结果以学校订单列表为准，扩展不会自动支付。
>
> 任务在当前设备运行。请保持 Chrome、预约标签页和设备处于运行状态。扩展由个人独立开发，未由上海交通大学发布或背书。

## 隐私规范

**单一用途：** 在用户选择的场馆、日期与时段内监控上海交通大学体育场馆预约网页的网球空场，并根据用户启用的任务提醒或提交网球场预约。

| 权限 | 说明 |
| --- | --- |
| `https://sports.sjtu.edu.cn/*` | 识别学校预约标签页、登录及预约页面的状态，读取网球场次，并根据用户配置在同一网站内操作预约表单。不会访问其他网站。 |
| `storage` | 在当前浏览器保存用户设置和限额冷却时间；以本次会话存储任务进度和结果，供后台休眠后恢复。 |
| `alarms` | 按设定时间唤醒后台执行检查及预约步骤；侧边栏关闭后仍可运行。 |
| `sidePanel` | 提供配置、开始、停止、候选空场和任务状态界面。 |
| `notifications` | 用本机系统通知报告符合条件的空场和任务结果。 |
| `offscreen` | 在侧边栏关闭时仍能通过扩展自带音频播放本机提示音。 |

远程代码：**否**，所有扩展代码随包提供。数据声明按后台字段如实披露本机处理的学校预约网站内容和相关页面 URL，以及在扩展中填写的预约偏好；无需声明扩展没有读取或保存的密码、认证 Cookie、支付资料等。数据用途和有限使用认证应与上面的隐私政策一致。

## 审核测试说明

> This is an independent tennis booking assistant for Shanghai Jiao Tong University. Open its side panel to inspect the two modes, the booking settings and the stop controls. Use “打开预约页” to open the school booking page. Live availability and booking require an authorized university jAccount, and no personal credentials are provided. For an end-to-end demo without any real order, run the repository's `extension/tests/browser_smoke.py` against its local mock booking page in an isolated Chromium profile. It covers monitoring, scheduling, booking, and cancellation without sending any booking requests to the university. Repository: https://github.com/VonSkylar/sjtu_tennis_toolkit

## 后续更新

1. 提升 `extension/manifest.json` 中的 `version`，在仓库根目录运行 `python -X utf8 extension/tools/package.py --store`。
2. 在开发者后台的**同一个项目**上传新 ZIP，并提交审核。发布后 Chrome 会自动检查并安装更新。
3. 若界面有变化，可用 `python -X utf8 extension/tools/store_assets.py` 重新生成截图。它使用临时浏览器资料和本地文件，不需要学校账号。

### 用 GitHub Actions 打包和送审

在 GitHub 仓库打开 **Actions → Release Chrome extension → Run workflow**，分支选 `main`。工作流会检查扩展、运行发布测试，并将 ZIP 和校验文件保存到本次运行的 **Artifacts → chrome-web-store-package**。选择 `operation` 决定本次操作。

| 选项 | 用途 |
| --- | --- |
| `package`（默认） | 生成可下载的商店 ZIP。可以立即使用。 |
| `check` | 检查 Google 授权，并读取现有商店条目的已发布版本。 |
| `submit` | 上传当前代码版本，并为现有条目提交审核。勾选 `publish_after_review` 会在审核通过后自动发布，取消勾选会暂存待发布。 |

工作流只由手动运行触发。送审会沿用商店条目的分发设置。已有版本待审或已过审待发布时，请先到商店后台处理该版本。送审操作运行期间请在 Actions 查看日志，避免同时在商店后台上传另一份包。

#### 第一次配置 Google 授权

1. 在 **Google Cloud Console** 创建或选择一个项目，启用 **Chrome Web Store API** 和 **IAM Service Account Credentials API**，创建一个专供发布使用的服务账号。然后在 **Chrome Web Store Developer Dashboard** 找到发布者设置里的 **Service account** 字段，填入该服务账号邮箱。该设置会授权服务账号管理这个发布者名下的条目。[Google 服务账号设置](https://developer.chrome.com/docs/webstore/service-accounts)
2. 在 Google Cloud 的 **Workload Identity Federation** 创建身份池和一个 **OpenID Connect** 提供方。签发方填 `https://token.actions.githubusercontent.com`。把 `google.subject` 映射为 `assertion.sub`，把 `attribute.repository` 映射为 `assertion.repository`。在提供方的属性条件里填下面这段，将信任范围限定为这个仓库 `main` 上的手动发布流程。[GitHub 与 Google Cloud 授权说明](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-google-cloud-platform)

   ```text
   assertion.repository == 'VonSkylar/sjtu_tennis_toolkit' &&
   assertion.ref == 'refs/heads/main' &&
   assertion.workflow_ref == 'VonSkylar/sjtu_tennis_toolkit/.github/workflows/chrome-web-store.yml@refs/heads/main' &&
   assertion.event_name == 'workflow_dispatch'
   ```

3. 在服务账号上将 **Workload Identity User** 角色授予该池里映射的仓库。把下面的 `PROJECT_NUMBER` 和 `POOL_ID` 换成实际值，项目编号使用 Google Cloud 显示的数字编号。[Google Cloud 服务账号授权说明](https://cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines#service-account-impersonation)

   ```text
   principalSet://iam.googleapis.com/projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/POOL_ID/attribute.repository/VonSkylar/sjtu_tennis_toolkit
   ```

4. 在 GitHub 仓库的 **Settings → Secrets and variables → Actions → Variables** 添加以下三个仓库变量。工作流通过 OIDC 取得临时凭证。

   | 变量 | 值 |
   | --- | --- |
   | `CWS_WORKLOAD_IDENTITY_PROVIDER` | 提供方的完整资源名 `projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/POOL_ID/providers/PROVIDER_ID` |
   | `CWS_SERVICE_ACCOUNT` | 第 1 步创建的服务账号邮箱 |
   | `CWS_PUBLISHER_ID` | Chrome 商店后台 **Publisher → Settings** 的 Publisher ID |

5. 回到 Actions，在 `main` 上运行 `check`。日志显示 `Connected to Chrome Web Store listing` 后，实际发版时再选择 `submit`。[Chrome Web Store API](https://developer.chrome.com/docs/webstore/using-api)
