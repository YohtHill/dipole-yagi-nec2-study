# Run the NEC-2 Study | 复现 NEC-2 仿真

Open the .nec decks in 4nec2 to inspect the geometry and radiation patterns. To regenerate the sweep outputs on Windows, install Python 3 and set NEC2_EXE to the 4nec2 solver path.

使用 4nec2 打开 .nec 模型，查看几何和方向图。若要在 Windows 上重新生成扫参输出，安装 Python 3 并设置 NEC2_EXE 为 4nec2 求解器的路径。

~~~powershell
$env:NEC2_EXE = 'C:/path/to/4nec2/exe/nec2dxs500.exe'
python scripts/part1_dipole_sweep.py
python scripts/part2_yagi_2el.py
python scripts/part3_yagi_directors.py
~~~

| Folder / 目录 | Design variables / 扫参变量 |
| --- | --- |
| [Part 1](../Part1/) | Dipole length and wire diameter / 偶极子长度与导体直径 |
| [Part 2](../Part2/) | Reflector length and spacing / 反射器长度与间距 |
| [Part 3](../Part3/) | Director length, spacing and multiple-director configurations / 引向器长度、间距与多引向器配置 |

Run in a working copy to preserve the included result snapshots. The scripts regenerate CSVs and replace the solver scratch directories. The three scripts completed in a clean copy on Windows and produced 108 NEC output files.

建议在工作副本中运行，以保留随仓库附带的结果快照。脚本会重新生成 CSV 并替换求解器的临时目录。三个脚本已在 Windows 干净副本中运行完成，共生成 108 个 NEC 输出文件。
