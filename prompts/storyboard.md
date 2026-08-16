# 分镜板模板（每集一份 → output/<项目>/E<集>/分镜.md）

> 8-12 格/集；每镜 5-10 秒；列名可中英混用（脚本按别名解析）。
> 填写后运行：`python3 scripts/pipeline.py storyboard <项目> --episode <n>` 生成 H3 提示词。

## 字段说明

| 字段 | 说明 | 词表 |
|---|---|---|
| 景别 | 镜头取景范围 | wide 远景 / medium-wide 全景 / medium 中景 / close-up 近景 / extreme close-up 特写 |
| 机位运动 | 镜头怎么动 | push in 推近 / pull back 拉远 / pan left-right 摇 / tracking 跟随 / orbit 环绕 / handheld 手持 / static 固定 |
| 时长 | 秒（默认 5） | 数字 |
| 角色 | 出现角色（与资产库 C 编号对应） | C01, C02 … |
| 场景 | 出现场景（S 编号） | S01 … |
| 灯光 | 光线情绪 | golden hour / overcast / neon / candlelight / moonlight / hard / soft |
| 对白/音效 | 台词或拟音 | 对白写台词；音效写"音效：风声" |
| 备注 | 情绪/转场/镜头意图 | 自由文本 |

## 模板（示例已填好，直接替换）

| 镜号 | 景别 | 机位运动 | 时长 | 角色 | 场景 | 灯光 | 对白/音效 | 备注 |
|---|---|---|---|---|---|---|---|---|
| 1 | wide | push in | 5 | 无 | S01 | golden hour | 环境音：风声 | 开场建立场景 |
| 2 | medium | static | 5 | C01 | S01 | golden hour | 对白：这里发生了什么 | 引入主角 |
| 3 | close-up | static | 5 | C01 | S01 | golden hour | 音效：心跳声 | 情绪铺垫 |
| 4 | medium | pan right | 5 | C01, C02 | S01 | golden hour | 对白：必须阻止你 | 冲突开始 |
| 5 | medium close-up | handheld | 6 | C01, C02 | S01 | overcast | 对白：我不会后退 | 高潮 |
| 6 | extreme close-up | static | 4 | C02 | S01 | overcast | 音效：雷声 | 反转 |
| 7 | wide | crane up | 5 | C01, C02 | S01 | overcast | 配乐渐强 | 收束 |
| 8 | medium | static | 5 | C01 | S01 | golden hour | 对白：明天见 | 钩子结尾 |

## 分镜设计口诀

- 开场 3 秒抓人（景别变化/运动镜头/冲突预告）
- 对白戏给近景+特写（H3 人脸 token 有限，越近越清晰）
- 动作戏给运动镜头（推/摇/跟/环绕）
- 双人同框锁手部（描述里写"两人的手保持静止"）
- 结尾留钩子（悬念/下集预告）
- 每镜问自己：这一镜的情绪是什么？机位/光线是否服务于它？
