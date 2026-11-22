# 300 MHz Dipole and Yagi Study | 300 MHz 偶极子与八木天线仿真

[English](#english) · [简体中文](#简体中文) · [Reproduce / 复现](docs/reproduce.md)

## English

A 4nec2/NEC-2 study that starts with a tuned centre-fed dipole, adds a reflector, and then varies director geometry to increase forward gain at 300 MHz. Each part includes editable NEC decks, CSV outputs and plots.

## 简体中文

使用 4nec2/NEC-2 建模，从中心馈电偶极子出发，加入反射器并扫描引向器尺寸与间距，比较 300 MHz 处的前向增益。三部分均包含可编辑的 NEC 模型、CSV 和仿真曲线。

![Comparison of simulated realized gain at 300 MHz / 300 MHz 仿真实现增益对比](Part3/plots/fig28_realized_gain_comparison_300MHz.png)

## 300 MHz results | 300 MHz 结果

| Model / 模型 | S11 (dB, 50 Ω) | Realized gain / 实现增益 (dBi) | Front-to-back / 前后比 (dB) |
| --- | ---: | ---: | ---: |
| [Tuned dipole / 调谐偶极子](Part1/nec/dipole_final.nec) | −15.28 | 1.99 | — |
| [2-element Yagi / 两单元八木](Part2/nec/yagi_2el_final.nec) | −11.26 | 6.37 | 4.87 |
| [3-element Yagi / 三单元八木](Part3/nec/yagi_3el_final.nec) | −12.37 | 7.78 | 10.74 |
| [11-element Yagi, 9 directors / 十一单元八木，含九根引向器](Part3/nec/yagi_9dir_best.nec) | −19.97 | 13.26 | 12.15 |

Realized gain includes mismatch loss relative to 50 Ω. For each Yagi the table uses gain toward the forward +x direction. Results are from electromagnetic simulation.

实现增益以 50 Ω 为参考计入失配损耗。八木天线各行使用 +x 方向的前向增益。表中数据均来自电磁仿真。
