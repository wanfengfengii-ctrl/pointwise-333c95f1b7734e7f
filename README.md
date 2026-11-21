# 包装线 V1 计数采集站

装盒线按班记录各通道的物理触发和异步整数原码。采集员停采后移交完整原据，班长按开班口径签报，夜班凭班报号核对实际产量。工程使用 Python 3.11 标准库和本地 SQLite。输入按明确事件序执行。

## 一个工作日

1. 班长登记 R1，按 A、B、C 清册以 2、1、1 定标，然后用 R1 开班 S1。
2. 后续登记的 R2 把 A 的比例设为 5。S1 继续使用冻结的 R1。
3. 控制器触发 A 的 M1、A 的 M2、B 的 M3。M2 的 11 先回。
4. 采集员停采，设备固定物理末位 3，先报告 M1、M3 未回。M3 回 0 后只欠 M1。
5. M1 回 7 后，设备按物理序封出整机成员与原件。站库逐件点收并提交接管回执。采集员核对首执后解除源端保管。
6. 班长签报。A 的 `7 × 2 + 11 × 2` 为 36 件，B 有一笔具名零原码，C 无触发。班合计为 36 件。
7. 关闭设备并重开站库。夜班按原号领取报告、原码、物理序和报告首执。

## 公开 Python 入口

从 `station` 导入 `Station` 和 `Source`。用本地站库文件路径创建 `Station(path)`，同一物理源采用一个在线 `Source(station)` 实例。`Source` 串行接纳物理事件。重开站库时，已有在线源会话和待移交源件可以继续使用。关闭源会话会释放其内存记录，历史报告由站库提供。

| 调用 | 返回与约束 |
| --- | --- |
| `station.rule(revision_id, channels, ratios)` | 保存有序清册及逐通道比例。相同修订复领，冲突拒绝。 |
| `source.open(shift_id, revision_id)` | 先持久保存冻结身份，再建立新班会话。同参复领身份，未知修订或冲突拒绝。 |
| `source.trigger(shift_id, channel, measurement_id)` | 返回从 1 开始的物理序。在采时同测次同通道复领。错班、错通道、换绑或停采后触发拒绝。 |
| `source.return_raw(shift_id, measurement_id, raw_code)` | 写入或复领该测次的第一份原件。停采后既有测次仍可回值。未知测次和异值拒绝。 |
| `source.stop(shift_id)` | 首次固定实际触发末位并关停新触发，重复返回原末位。 |
| `source.readout(shift_id)` | 已停班有欠件时返回 `AwaitingReturns` 及具名缺项，排空后返回可重领的 `WholeReadout`。 |
| `station.receive(shift_id, readout)` | 以冻结身份和设备清单核对全部物理位置。提交实收头、原件和首执后返回 `CustodyReceipt`。同件同内容复领。 |
| `source.confirm(readout_id, receipt)` | 独立查询本站已提交首执，匹配封件和班身份后返回已确认的保管记录。错件或未提交首执保留源件。 |
| `station.issue(shift_id)` | 凭已提交的实收签发班报和首执，同时结班。重投复领原报告。 |
| `station.retrieve(report_id)` | 读取固定汇总、逐件定标结果、实际原据及首执。未知报告号返回 `None`。 |

`station.revision`、`station.phase`、`station.received`、`station.custody_receipt` 和 `source.custody` 可用于查询已发生的业务状态。标识为非空白字符串，原测次在班内唯一。比例为严格正整数，原码为严格非负整数。空值表示未收到原码，0 表示已收到有效原件。字段、绑定、阶段或重投冲突使用 `ValueError`，SQLite 提交错误由调用方收到。失败的实收或签发不发布新首执，可沿原件重试。

报告使用 Python 精确整数，按物理序保存原件和定标明细，按冻结清册列出通道汇总。站库使用十六进制文本保存业务整数。`Station.initialize()` 补齐表结构，保留用户规程、冻结班次、实收和历史报告。

## 完整回归与样例

```text
python3 -B check_project.py
python3 -B replay.py
```

完整回归包括冻结规程、冲突回值、乱序排空、错执保管、实收回滚、零值及空班、签报回滚、断源领取、重复初始化和完整工作日。demo 在临时目录创建站库，按 `examples/workday.json` 回放，核对待回清单、36 件手算结果及断源取得的原据和首执，并输出一行 `POINTWISE_SCENARIO` JSON。断言失败时进程返回非零退出码。
