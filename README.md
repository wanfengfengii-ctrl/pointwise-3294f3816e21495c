# 光谱零点校正交班

涂层材料实验室的白班从光谱仪接收有序测次，夜班在独立的离线库核定校正读数。下一班按成果号领取当时签出的明细、出处、合计和首执。全部强度和零点使用同一整数单位。

## 一天的交班

1. 操作员导入设备原批，以批号、测次号和采样位置保存原强度与原件出处。
2. 制表员按测次身份选行，登记相对零点引用和可选默认。
3. 制表员用指定台件与挂载试配，读取校正值、缺测和出处。
4. 制表员冻结并发行选定模板修订。随后改动草稿可形成另一修订。
5. 台位管理者独立冻结并发行台件，固定各位置的零点或停用条目。
6. 夜班实收模板件和各台件，取得可用于清单的实收号。之后只需要离线库。
7. 夜班按指定挂载套用每个清单项。结果沿清单和模板行序排列。
8. 夜班签发固定成果、有效合计和成功首执。
9. 下一班按号复领取用。采用改发来件时另作一份成果。

## 运行

使用 Python 3.11 标准库，从项目根目录运行。

```sh
python3 -B check_project.py
python3 -B demo.py
```

控制台在物化时提供 `check_project.py`。直接执行整套回归可用 `python3 -B -m unittest discover -s tests -t . -p 'test_*.py'`。`check_project.py` 先跑全集回归，再跑 V1 与 V2 两个夹具，任一失败以非零退出。演示从 `samples/` 读取固定输入，在临时目录建立两套 SQLite 库，试配后关闭并移除发行库，再用独立离线库签存并重开复领。两台供值时读数为 17、13，合计 30。西台停用时保留缺测，合计 17。西台确实缺条目时采用模板默认 2，读数为 17、18，合计 35。演示随后另作一份 V2 限行交件，按名册断库重算第 1、3、5 行为 17、缺测、18，小计 35，并展示漏证和缺证拒收。

## Python 接口

业务接口接收调用方打开的 `sqlite3.Connection`。在没有外层事务时调用写接口，接口自行提交或回滚。查询可在重开的库上使用。低层 `store_snapshot` 与 `store_first_receipt` 由签发事务调用。

| 职责 | 入口和结果 |
| --- | --- |
| 原批 | `source.ingest.ingest(db, batch_id, rows)` 接收顺序表，每行含 `measurement_id`、整数 `strength` 和原件位置 `source`，返回 `ImportReceipt`。`source.batches.load_batch(db, batch_id)` 按采样顺序返回原读。 |
| 初始化 | `source.initialize.initialize_source(db, batches)` 接收含 `batch_id`、`rows` 的样例批表，返回新导入批的首执。既有同号批优先，重复执行只补缺少的批。 |
| 制表 | `template.draft.build_draft(name, rows)` 接收含 `batch_id`、`measurement_id`、`reference` 的有序行。可给 `reference_source` 和 `default`，默认对象包含整数 `value` 和 `source`。`draft.replace_rows(rows)` 可替换草稿选择。 |
| 试配 | `template.preview.preview(db, draft, bench_revision, mount)` 返回逐行试配结果。`bench_revision` 可由 `freeze_bench` 或 `get_bench_revision` 取得。 |
| 发模板 | `template.revision.freeze_template(db, draft, revision)` 固定当前选择，`template.issue.issue_template(db, name, revision)` 返回原发件 `Envelope`，含 `number` 和可传送的 `packet` 字节。限行复核另接受仅限关键字的 `version=1`，可取 1 或 2，见 DISCLOSURE.md。 |
| 发台件 | `bench.revision.freeze_bench(db, bench, revision, rows)` 接收含 `path`、`state`、`source` 的条目，`state` 为 `value` 时须给整数 `value`，为 `disabled` 时 `value` 为空或省略。`bench.issue.issue_bench(db, bench, revision)` 按修订发件，同样接受仅限关键字的 `version=1`。 |
| 实收 | `processing.intake.receive(db, packet)` 返回整数实收号。`get_received(db, receipt_id)` 可查实收件。V1 与 V2 包均可实收。 |
| 加工 | `processing.apply.run(db, items)` 接收非空有序 `ApplicationItem(template_receipt, bench_receipt, mount)` 表，返回 `ApplicationResult`。每行含套用序、实收号、两类修订、模板行序、原测、所查路径、整数读数或缺测及零点依据。 |
| 签发与复领 | `report.publish.publish(db, request_id, result)` 返回 `FirstReceipt`，`report.readback.read(db, report_id)` 返回 `ReadReport`，含 `snapshot` 和 `first_receipt`。同一签发请求重试时，完整结果相等则返回原首执，内容不同则拒绝。`report.readback.disclose(db, report_id, ordinals)` 导出限行交件字节，见 DISCLOSURE.md。 |
| 限行复核 | `processing.apply.verify_disclosure(anchors, roster, packet)` 不带数据库，按另路锚、名册和局部件重算获准行，见 DISCLOSURE.md。 |

## 数据与错误语义

- 原读和冻结修订的身份一经登记即固定。相同强度可以来自不同测次。空批、批内重复测次、非法数值、重复冻结同一身份和重复导入均拒绝。未知原批、原测、修订、实收或成果以 `KeyError` 报告。结构错误和身份冲突以 `ValueError` 报告。
- 虚拟台件路径以 `/` 分段，空挂载和 `.` 表示根，空段和 `.` 跳过，`..` 逐段上移。解析中一旦越根即拒绝，后续路径段无法恢复资格。禁止绝对路径、反斜杠和空字符。台件中两个条目规范化至同一路径时拒绝。
- 一条实例行有四种校正依据。有效台件条目（含整数零）采用实际条目值与出处。停用时记录该条的出处并保留空读数。目标缺条目且有默认时记录模板默认依据，缺条目且无默认时记录所查位置并保留空读数。有效读数等于原强度减零点，合计只包含有效读数，全部缺测时合计为零。
- V1 包为 UTF-8 JSON，外层包含 `version`、`kind`、`number`、`digest` 和 `body`。完整性摘要为其余四个字段规范 JSON 的 SHA-256。`kind` 区分模板与台件，`number` 由名称和修订组成。每类同号、同规范内容重投可取原实收号；同号异件和非法正文拒收。包正文及成果快照的业务整数采用规范有符号十六进制文本，Python 接口返回整数。
- V2 包沿用同一外层与冻结正文记录，但 `version` 为 2，`digest` 为 64 个小写十六进制字符组成的发行锚。锚在首次发件时固定，绑定 V2、件种、发行号和冻结正文，产生时尚不知披露行或套用挂载。同一修订同版本重领原件；已发修订换版本请求以 `ValueError` 拒绝。V1 原入口与历史复领保持原样，旧件不可补作披露。
- 试配和加工只读。清单任一项非法时加工拒绝整单。`PublishError` 表示签存阶段的 SQLite 失败，当次成果和首执一并回滚。已签成果按原号读取保存值。

限行复核的起件条件、交件形状、断库核验与拒收语义见 DISCLOSURE.md。
