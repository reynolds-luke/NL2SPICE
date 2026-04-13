
# Performance Metrics for LLM Netlist Generation

## Syntax & Validity
- ***Parse Success Rate***: % of generated netlists that parse without errors

## Circuit Performance
- ***Filter Response Match***: Comparison of magnitude/phase response to target specs
- ***Passband Ripple***: Deviation from target ripple specification
- ***Cutoff Frequency Error***: % error in -3dB frequency
- ***Attenuation Accuracy***: Stopband attenuation vs. specification

## Generation Quality
- **Completeness**: % of netlists with all required components
- **Simulation Convergence**: % of netlists that simulate successfully

## Meta Metrics
- **Token Efficiency**: Tokens used per valid netlist generated
- **Generation Time**: Average time to produce output

## Look into this:
- **Redundancy**: Detection of unnecessary components or connections

## TO-DO
- Maybe store the model outputs weights so if we want to check more parameters later on.
- 
