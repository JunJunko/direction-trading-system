# 主板非 ST 全量回测口径

运行 `python scripts/backtest_mainboard.py`。使用环境中的 TUSHARE_TOKEN，原始响应缓存于 `data/raw/tushare`，输出保存于独立的 `runs/*-mainboard-v3` 目录。下载失败不继续计算，也不把失败请求当作停牌；修复数据问题后重新运行可复用已完成请求。

本次请求考核 2025-10-08 至 2026-10-07；交易日沿用上一轮三只银行股快照，实际 2025-10-09 至 2026-09-30，共 241 日。2023-01-03 起的数据只做因果预热，不继承预热交易或仓位，考核开始时账户空仓。

股票池取 stock_basic 的 L、D、P 状态，market 为主板且代码为沪市 60 或深市 00 的 A 股，上市区间与考核区间相交。候选 3,214 只，包含 17 只后来退市的股票。每个考核交易日取得 stock_st 历史名单，信号日与下一交易日执行时分别检查上市、退市和 ST 资格；缺失 ST 覆盖不能交易。ST 阶段的行情仍保留用于结构识别，已持仓股票变 ST 继续由原策略管理，而非自动强制清仓。

所有候选共用一个账户；保持 double_bottom_v3 默认配置，100 万本金、单笔风险 0.5%、组合风险 2%、最多 5 只、单股权重 10%、总仓位 50%、扣除成本后的计划盈亏比严格大于 3。结构止损逐步上移，目标价只是入场筛选；没有自动分批减仓。此版本不包含人工阶段策略，不应把它的结果描述为完整哲学系统的验证。

日线、复权因子、涨跌停价按日期取得全市场数据后筛选候选；价格缺少所需因子或限价时停止。缺少日线可能是停牌，不使用前值制造行情。因子按当时可知值归一化，账户采用合成总收益股数调整；这与真实分红、送转、配股现金流有差别。日线内买卖顺序不明确时按引擎保守规则执行。

下载脚本保存 bars.csv、calendar.json、universe.json、config.json、source，以及交易、委托、拒单、净值、预热事件。运行 `python scripts/summarize_mainboard.py <输出目录>` 补充中文报告、数据与源码哈希、每日合资格股票数量及期末缺失行情持仓检查。

离线复现可以使用当前仓库入口：

```powershell
python run.py csv --csv <输出目录>/bars.csv --calendar <输出目录>/calendar.json --universe <输出目录>/universe.json --config <输出目录>/config.json --evaluation-start 20251008 --evaluation-end 20261007
```

全量性能优化不改变策略规则：周线增量缓存遇复权因子变化重建，并保持原始浮点运算顺序。测试覆盖因子变化、停牌间隔、跨周补算以及历史长度缩短；原三只银行股的决策、交易和统计结果已逐项核对一致。

数据接口说明：[股票列表](https://tushare.pro/document/2?doc_id=25)、[历史 ST](https://tushare.pro/document/2?doc_id=397)、[日线](https://tushare.pro/document/2?doc_id=27)、[复权因子](https://tushare.pro/document/2?doc_id=28)、[涨跌停价](https://tushare.pro/document/2?doc_id=183)。
