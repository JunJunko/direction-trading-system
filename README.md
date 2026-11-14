# A 股方向交易系统

基于 ebook 中的交易三观、小亏大赚、时间架构与节奏点建立的可扩展研究实现。第一条插件是“周线双底确认 + 日线反抽重启”。

## 运行

Python 3.11+。演示、CSV 回放和测试只用标准库。

```powershell
python run.py demo
python -m unittest discover -s tests -v
```

Tushare 模式需要安装 SDK，并在当前进程环境提供 `TUSHARE_TOKEN`。不将 token 写入配置、报告或提交到代码仓库。

```powershell
python -m pip install -e ".[tushare]"
python run.py tushare --symbols 000001.SZ 600000.SH 600036.SH --start 20230101 --end 20260930
```

接口权限不足或限流会报错，不自动替换成模拟数据。

回放已保存的快照（将路径替换为实际运行目录）：

```powershell
python run.py csv --csv runs/<运行编号>/bars.csv --calendar runs/<运行编号>/calendar.json --config runs/<运行编号>/config.json
```

每次运行生成独立 runs 目录，包含 report.html、manifest.json、config.json、summary.json、calendar.json、bars.csv、decisions.csv、orders.csv、trades.csv、equity.csv。期末持仓按市值记录，不强制平仓；已平仓统计和未实现收益分开。

## 文档

- [候选合格标准与同底失效传递：42组全量回测、收益归因和K线核验](runs/20261109-qualified-candidates-verified/report.html)
- 本轮研究配置：[外肩至少3日、相邻主段10%＋同底失效传递＋周线W](configs/experiments/ihs_v11_quality_10_guard_with_weekly_w.json)。短肩和换锚点行为受到限制，但收益降至4.87%，未替换默认策略；详见上述报告。
- [候选排序与消费规则：3,214只股票、20组回测和逐笔K线核验](runs/20261109-candidate-policy-full/report.html)
- 本轮常规成本较优的研究配置：[时间平衡排序、只提交首选＋周线W](configs/experiments/ihs_v10_balance_single_with_weekly_w.json)。收益小幅改善，但未证实形态误判改善，详见对照报告。
- [头肩底 v1：截图规则、独立配置与风控边界](docs/inverse-head-shoulders-v1.md)
- [头肩底截图算法审查：包络形态漏检与几何偏差](docs/inverse-head-shoulders-diagram-audit.md)
- [头肩底 v2：包络搜索、头部突出度与相对尺度修正](docs/inverse-head-shoulders-v2.md)
- [头肩底 v3：突破后等待回踩颈线确认](docs/inverse-head-shoulders-v3-retest.md)
- [哲学与边界](docs/philosophy.md)
- [模块、扩展和执行约定](docs/architecture.md)
- [双底规则与书中依据](docs/double-bottom-v1.md)
- [策略变更流程](docs/strategy-change-process.md)
- [逐笔拒绝审计与 v2 修复](docs/double-bottom-audit-20261007.md)
- [双底识别完整性与 v3 修复](docs/double-bottom-review-v3.md)
- [v4 候选：停牌识别与反抽状态修复](docs/double-bottom-v4.md)
- [v5.1 修复：持续方向、N字量度与节奏点计划](docs/double-bottom-v5.md)
- [v5.2 候选：整体双底、横向反抽与小级别触发](docs/double-bottom-v5-2.md)
- [v5.3 候选：活动调整与持仓退出纠错](docs/double-bottom-v5-3.md)
- [v5.4 候选：自动准入与核心持仓状态](docs/double-bottom-v5-4.md)
- [v5.5 候选：当前上涨段与及时结构保护](docs/double-bottom-v5-5.md)
- [v5.10 候选：日线核心更新、节奏归属与有效压力](docs/double-bottom-v5-10.md)
- [v5.11.2 候选：波段归属、生命周期、触发价消费与持仓尺度](docs/double-bottom-v5-11.md)
- [v5.12 候选：日线双底方向可选配置](docs/double-bottom-daily-direction.md)
- [v5.13 候选：支撑区域与近支撑入场](docs/double-bottom-support-zone.md)
- [v5.14 候选：支撑附近止跌确认入场](docs/double-bottom-support-rebound.md)
- [v5.15 候选：支撑上沿回踩与窄防守带](docs/double-bottom-support-band.md)
- [冻结基线与21组单规则对照（含全量差异及盲审）](runs/20261010-140123-double-bottom-rule-ablation/report.html)
- [主板非ST全量回测口径](docs/mainboard-backtest.md)

## 验证结果（2026-10-07）

构造样例验证两次入场、亏损退出、跟踪止损和盈利退出；不用于估计策略收益。真实 Tushare 的三个固定样本（2023-01-01 至 2026-09-30）产生 13 次双底突破识别、6 次入场意图，首次运行全部被净报酬风险比或成交条件拒绝。这说明约束在执行，不构成盈利结论。

已加入主板逐日上市/ST资格及全量共享账户回测。v5提供持续上级方向、日线N字目标、较小节奏点、条件计划复核和人工阶段策略接口。当前全量快照只有日线，尚未提供历史人工阶段记录及真实小时行情；因此v5日线结构实验不代表完整三周期系统验证。真实公司行动现金结算与实盘执行仍未实现。

默认配置 `configs/double_bottom_v3.json` 保留为旧基准，不能视为原书完整策略。修复版需显式指定 `configs/experiments/double_bottom_v5.json`，其中人工阶段记录为空时禁止开仓。数据只有日线时可显式运行 `double_bottom_v5_structure.json` 的结构实验；这个研究声明不能用于替代生产阶段门控。原运行快照始终保留。

早期三个银行股快照中v2产生3个入场候选，v3产生2个，均未成交；最新一年主板全量v3基准产生5次买入。测试覆盖确认因果性、独立N字空间、计划复核、阶段门控与资金执行；当前55项测试通过。详情见对应版本文档及独立运行报告。

```powershell
python scripts/audit_rejections.py runs/20261007-195617-072350-tushare
```

审计脚本不会覆盖原运行。对于缺少详细审计日志的旧版，仅重建零成交的平仓账户；不会虚构已有持仓的历史风险状态。

## Tushare 官方接口依据

- [日线行情](https://tushare.pro/document/2?doc_id=27)
- [复权因子](https://tushare.pro/document/2?doc_id=28)
- [每日涨跌停价格](https://tushare.pro/document/2?doc_id=183)
- [交易日历](https://tushare.pro/document/2?doc_id=26)
