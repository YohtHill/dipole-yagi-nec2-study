# Design Method and Reproduction

[简体中文](reproduce.zh-CN.md) · [Project home](../README.md)

1. Start with a 0.480 m centre-fed dipole. Sweep length, tune to 0.457 m, and then vary wire diameter. The final wire diameter is 8 mm. The coursework report gives −10 dB crossings near 286.06 MHz and 316.51 MHz.
2. Add a 0.460 m reflector 0.200 m behind the driven element. Compare reflector length and spacing while keeping the driven element geometry fixed.
3. For the 3-element design, add one 0.400 m director 0.200 m in front. For the final 11-element design, use nine directors tapering from 0.420 m to 0.380 m. The first is 0.150 m ahead of the driven element and the rest are spaced by 0.200 m.
4. Use `Γ = (Zin − 50 Ω)/(Zin + 50 Ω)` for matching. Realized gain adds `10 log10(1 − |Γ|²)` to the NEC gain. Front-to-back ratio compares gain along opposite boom directions.

| Part | Editable decks | Results |
| --- | --- | --- |
| Dipole | [NEC files](../Part1/nec/) | [data](../Part1/data/) and [plots](../Part1/plots/) |
| Reflector | [NEC files](../Part2/nec/) | [data](../Part2/data/) and [plots](../Part2/plots/) |
| Directors | [NEC files](../Part3/nec/) | [data](../Part3/data/) and [plots](../Part3/plots/) |

Open the models in 4nec2 to inspect geometry and radiation patterns. To rerun the scripts, use Python 3 and the Windows NEC-2 solver. Run in a separate working copy because the scripts regenerate CSV outputs and replace solver scratch directories.

~~~powershell
$env:NEC2_EXE = 'C:/path/to/4nec2/exe/nec2dxs500.exe'
python scripts/part1_dipole_sweep.py
python scripts/part2_yagi_2el.py
python scripts/part3_yagi_directors.py
~~~

The three scripts were exercised together in a clean workspace and produced 108 solver outputs. Headline values come from the frequency-sweep CSVs and the broadband table in the coursework report.
