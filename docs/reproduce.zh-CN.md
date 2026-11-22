# 设计方法与复现

[English](reproduce.md) · [项目首页](../README.zh-CN.md)

1. 从总长 0.480 米的中心馈电偶极子开始，扫描长度使其调谐至 0.457 米，再比较不同导体直径。最终导体直径为 8 毫米。课程报告给出的 −10 dB 交点约为 286.06 MHz 与 316.51 MHz。
2. 在有源振子后方 0.200 米处增加长 0.460 米的反射器。在振子几何尺寸固定时，比较反射器长度和间距。
3. 三单元模型在前方 0.200 米处加入一根长 0.400 米的引向器。最终十一单元设计加入九根引向器，长度由 0.420 米递减至 0.380 米。首根位于有源振子前方 0.150 米，其余间距为 0.200 米。
4. 通过 `Γ = (Zin − 50 Ω)/(Zin + 50 Ω)` 计算匹配；在 NEC 增益上加 `10 log10(1 − |Γ|²)` 得到实现增益。前后比比较沿天线主轴相反两方向的增益。

| 阶段 | 可编辑模型 | 结果 |
| --- | --- | --- |
| 偶极子 | [NEC 文件](../Part1/nec/) | [数据](../Part1/data/)与[曲线](../Part1/plots/) |
| 反射器 | [NEC 文件](../Part2/nec/) | [数据](../Part2/data/)与[曲线](../Part2/plots/) |
| 引向器 | [NEC 文件](../Part3/nec/) | [数据](../Part3/data/)与[曲线](../Part3/plots/) |

用 4nec2 打开模型可查看几何与方向图。在 Windows 上运行脚本，需要 Python 3 和 NEC-2 求解器。建议使用工作副本，脚本会重新生成 CSV 并替换求解器临时目录。

~~~powershell
$env:NEC2_EXE = 'C:/path/to/4nec2/exe/nec2dxs500.exe'
python scripts/part1_dipole_sweep.py
python scripts/part2_yagi_2el.py
python scripts/part3_yagi_directors.py
~~~

三个脚本已在干净的工作副本中依次运行，生成了 108 份求解输出。首页数值来自扫频 CSV 和课程报告中的带宽表。
