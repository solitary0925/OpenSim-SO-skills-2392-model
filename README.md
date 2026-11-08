# OpenSim SO skills for Gait2392

v0.3.0 用于兼容 Gait2392 / CGM24 原膝关节模型的步态支撑期静态优化。

- 支持全身 IK／RRA 对照，以及由 IK 规定骨盆运动、只加载目标脚力台的单腿 SO。
- 开跑前选择原版 Gait2392 最大等长肌力，或将 Rajagopal 2016 的对应最大等长肌力移植到 Gait2392 工作副本。
- 保存原生肌肉力与激活，按原始时间和支撑期百分比复核失败帧、激活触顶和关节储备。

## 使用

在 Codex 中，将本仓库内容作为 `opensim-vicon-so` 技能目录安装，再调用 `$opensim-vicon-so`。也可在具备 OpenSim 4.5 CLI、OpenSim Python API、NumPy 和 SciPy 的环境中直接运行脚本。仓库提供配置示例，运行需要自行准备兼容的模型、运动与已核查的外力。

- [技能入口](SKILL.md)
- [中文工作流](references/workflow.md)
- [全身配置和命令](references/execution.md)
- [单腿配置和命令](references/single-leg.md)
- [验证范围](references/validation.md)
