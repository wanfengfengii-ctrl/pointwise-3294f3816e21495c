# 已签交班的限行复核

原接口、台件路径规则、扣零规则与整件交班见 README.md。限行复核给异地人员提供指定报告行的原据。批准名册由可信交班人员另路交付，固定获准行身份。发行锚由原发行方另路交付。局部件是待核材料，复核时只使用传入的名册、锚和局部件。导出方可使用签发库内的完整实收件，发行库关闭后仍可出件。

## 固定发行

给 `template.issue.issue_template(db, name, revision)` 与 `bench.issue.issue_bench(db, bench, revision)` 增加仅限关键字的 `version=1`，可取整数 1 或 2。V2 沿用 `Envelope` 的字段、两类发行编号和完整正文记录。`Envelope.version` 为 2，`Envelope.digest` 为 64 个小写十六进制字符组成的发行锚。发行锚随首次发件固定，绑定 V2、件种、发行号和冻结正文，产生时尚未选择披露行或套用挂载。同一修订同版本重领原件，已发修订换版本请求抛 `ValueError`。V1 按原约定收发。

`processing.intake.receive(db, packet)` 接受完整 V2 件，核对冻结正文、件号和摘要。同件复领实收号，同号异件仍拒绝。V2 实收后沿用 `run`、`publish` 和 `read`，可在其既有合法挂载下套用。摘要及局部证明的组织和编码由实现决定。导出无需原发行方为某次披露另出凭证。

## 签后出件

`report.readback.disclose(db, report_id, ordinals)` 以已签报告为准，返回 UTF-8 JSON `bytes`。`ordinals` 为非空无重复的列表或元组，取报告内从 1 起算的整数序位，输出按入参顺序。未知成果抛 `KeyError`，非法序位或所选行引用旧件抛 `ValueError`。选中行所引用的模板、台件均须为 V2。其他行仍可按原接口复领。

交件外层为 `{"report_id": ..., "rows": [...]}`。每行身份字段为 `ordinal`、`template_number`、`template_row`、`bench_number`、`mount`，分别表示报告序位、模板发行号、模板内从 1 起算的行位、台件发行号和原套用的规范挂载。发行号沿用各自原件。行另含以下四项。

- `template` 是该原行的 `FrozenTemplateRow.to_record()` 记录，包含原读、规则及出处。
- `template_proof` 是该原行在指定模板件及行位上的证据。
- `entry` 是实际查找路径的 `BenchEntry.to_record()` 记录，确实缺条目时为 `null`。
- `bench_proof` 是该路径在指定台件中的条目证据或缺条目证据。

两类证明字段须存在，由实现定义其 JSON 表示。证明可含核验所需的局部结构数据。交件中的原读明文仅限获准行，台件条目明文仅限这些行实际查找的路径。不得附完整键索引。

## 断库复核

`processing.apply.verify_disclosure(anchors, roster, packet)` 无数据库参数。`anchors` 是另路保管的字典，以 `(kind, number)` 为键，值为对应 V2 发行锚。`roster` 是独立取得的批准名册，外层与交件相同，每行只有上述五个身份字段，序位不重且有序。名册给出的挂载已规范化。先核对来件与整个名册的报告号、行序及身份，再逐行从已验证的模板引用和名册挂载解析实际规范路径。以该路径核对指定台件的存在或缺失，之后沿用原来的零点和缺测规则。相同原件事实可供多个获准行各自核验，各行仍按自己的名册身份计入小计。

成功返回 `{"report_id": int, "rows": [...], "total": int}`。每行字段为 `ordinal`、`source`、`raw_strength`、`reference`、`reference_source`、`strength`、`zero`。`source` 与 `zero` 分别采用 `asdict(ObservationSource)` 与 `asdict(ZeroDecision)` 的字典形状，数值为 Python 整数，空值用 `None`。`strength` 是重算后的读数或缺测，`total` 仅求有效读数之和。来件格式错误、重复字段、错版、错位、缺证、证据矛盾、名单不齐或范围超出均抛 `ValueError`，无部分结果。改写 `entry` 为 `null` 仍须通过同一确切路径的缺条目核验。

## 样例与核验

`disclosure_fixture.py` 把现有样例中的 M1、M2 一同编进模板。两行原强度各为 20，原件出处各异。依次套用东台零点 3、西台停用修订和西台确实缺目标条目的修订。两个西台修订都含无关位置条目，供核对局部披露。V1 夹具可直接运行 `python3 -B disclosure_fixture.py`，输出原报告合计 70 和选定行的原结论。做新链验证时，向 `prepare` 传入选用 `version=2` 的发行可调用对象，通过 `issuance_anchors` 在出件前取得发行锚，按 `approval` 的形状独立传递名册。

选第 1、3、5 行后，断库复核读数依次为 17、缺测、18，小计为 35。停用行保留 `west-lockout:12`，默认行保留 `worksheet/coat:B4`。去掉停用材料、换入另一修订的缺失证明、用同值 M2 替换 M1 或添加未获准行时拒绝。正常出件不带 M2 的原据或无关台件条目。

联合核验保留全部原回归，核验失败以非零状态退出。沿用 `.pointwise-runtime.json` 的版本 1 和 `cli` 类型，`setup` 为准备命令参数的数组列表，`verify` 和 `demo` 各登记一条命令的参数数组。`verify` 运行原回归和限行复核联合核验，`demo` 展示真实限行出件、漏证拒绝和断库重算结果。

## 本实现的证明与锚

两类证明的 JSON 表示由本实现定义，均为局部结构数据，不含完整键索引。

- `template_proof` 为 `{"index": 行位, "count": 件内行数, "siblings": [小写十六进制, ...]}`。冻结模板的发行锚是有序二叉 Merkle 树根，叶按 `(V2, 件种, 发行号, 总行数, 行位, 原行记录)` 规范 JSON 的 SHA-256 生成，相邻子树按 RFC 6962 方式合并，故任意行数（含非 2 的幂）都可出证。
- `bench_proof` 为 `{"path": 实际查找路径, "siblings": [256 个小写十六进制, ...]}`。冻结台件的发行锚是 256 层稀疏 Merkle 树根，键为 `sha256(路径)`，叶区分“该路径有该条目”与“该路径无条目”；缺条目本身可被证明，因此只有确证该路径无条目时才允许落到模板默认。
- 校验时先逐项比对来件与名册的五个身份字段和行序，再用发行锚验证局部证明，随后沿名册挂载解析规范路径、核对条目或缺条目，最后沿用 README 的零点与缺测规则重算读数并求有效小计。任何缺字段、重复字段、错版、错位、证据矛盾、名单不齐或范围超出都在返回前抛 `ValueError`，不产生部分结果。

`report.readback.disclose` 只导出所选行。`entry` 仅在所选行实际查到的路径上有明文，确缺条目时为 `null`；未选行的原读和其他台件条目不出现在交件中。V1 已签成果可用 `disclose` 时，因所选行引用 V1 件而抛 `ValueError`，其余行仍可经 `read` 按原接口复领。
