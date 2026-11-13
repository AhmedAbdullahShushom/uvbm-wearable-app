%% AUTO-BUILDER FOR UBVM SIMULINK MODEL (UBVM_System_Model.slx)
% Run this script in MATLAB to automatically construct, wire, and run the 
% working Simulink model (.slx) of the Ultrasonic Bladder Volume Monitor (UBVM).

clear; clc; close all;

modelName = 'UBVM_System_Model';

if bdIsLoaded(modelName)
    close_system(modelName, 0);
end
if exist([modelName, '.slx'], 'file')
    delete([modelName, '.slx']);
end

fprintf('Building Simulink model: %s.slx ...\n', modelName);
new_system(modelName);
open_system(modelName);

set_param(modelName, ...
    'Solver', 'ode4', ...
    'FixedStep', '1e-8', ...
    'StopTime', '150e-6');

Lm = 28.5e-6;             % PZT Motional Inductance (28.5 uH)
Cm = 213.5e-12;           % PZT Motional Capacitance (213.5 pF)
Rm = 52;                  % Air-Backed Radiation Resistance (52 Ohms)

num_single = [Rm, 0];
den_single = [Lm, Rm, 1/Cm];
num_pzt = conv(num_single, num_single);
den_pzt = conv(den_single, den_single);

tau_opa = 1 / (2 * pi * 10e6);
tau_lpf = 1 / (2 * pi * 5.88e6);

add_block('simulink/Sources/Pulse Generator', [modelName, '/2MHz_Carrier'], ...
    'Position', [40, 60, 90, 100], 'Amplitude', '40', 'Period', '0.5e-6', 'PulseWidth', '50', 'PhaseDelay', '0');
add_block('simulink/Sources/Constant', [modelName, '/DC_Offset_20V'], ...
    'Position', [40, 125, 80, 155], 'Value', '-20');
add_block('simulink/Math Operations/Add', [modelName, '/Bipolar_Shift'], ...
    'Position', [120, 75, 150, 115], 'Inputs', '++');
add_block('simulink/Sources/Step', [modelName, '/5_Cycle_Gate_2p5us'], ...
    'Position', [120, 145, 150, 175], 'Time', '2.5e-6', 'Before', '1', 'After', '0');
add_block('simulink/Math Operations/Product', [modelName, '/MAX14808_Pulser'], ...
    'Position', [190, 90, 225, 135]);

add_block('simulink/Continuous/Transfer Fcn', [modelName, '/AirBacked_PZT_2MHz'], ...
    'Position', [265, 85, 395, 140], 'Numerator', mat2str(num_pzt), 'Denominator', mat2str(den_pzt));

add_block('simulink/Math Operations/Gain', [modelName, '/TR_Switch_Leakage'], ...
    'Position', [450, 35, 510, 65], 'Gain', '0.012');
add_block('simulink/Continuous/Transport Delay', [modelName, '/Anterior_Wall_32us'], ...
    'Position', [450, 95, 490, 125], 'DelayTime', '32e-6');
add_block('simulink/Math Operations/Gain', [modelName, '/Anterior_Atten'], ...
    'Position', [520, 95, 580, 125], 'Gain', '0.00075');
add_block('simulink/Continuous/Transport Delay', [modelName, '/Posterior_Wall_138us'], ...
    'Position', [450, 160, 490, 190], 'DelayTime', '138e-6');
add_block('simulink/Math Operations/Gain', [modelName, '/Posterior_Atten'], ...
    'Position', [520, 160, 580, 190], 'Gain', '0.00028');
add_block('simulink/Sources/Band-Limited White Noise', [modelName, '/Thermal_Noise'], ...
    'Position', [520, 220, 560, 250], 'Cov', '0.8e-14', 'Ts', '1e-8');
add_block('simulink/Math Operations/Add', [modelName, '/LVOUT_Node'], ...
    'Position', [625, 70, 660, 210], 'Inputs', '++++');

add_block('simulink/Continuous/Transfer Fcn', [modelName, '/OPA357_Amp_Gain10'], ...
    'Position', [700, 115, 800, 165], 'Numerator', '[10]', 'Denominator', sprintf('[%.6e, 1]', tau_opa));
add_block('simulink/Continuous/Transfer Fcn', [modelName, '/RC_LPF_5p88MHz'], ...
    'Position', [840, 115, 940, 165], 'Numerator', '[1]', 'Denominator', sprintf('[%.6e, 1]', tau_lpf));
add_block('simulink/Discontinuities/Relay', [modelName, '/MAX941_Comparator'], ...
    'Position', [990, 120, 1035, 160], 'OnSwitchValue', '0.038', 'OffSwitchValue', '0.012', 'OnOutputValue', '5.0', 'OffOutputValue', '0.0');

add_block('simulink/Sinks/Scope', [modelName, '/UBVM_Oscilloscope'], ...
    'Position', [1110, 75, 1155, 145], 'NumInputPorts', '3');
add_block('simulink/Sinks/To Workspace', [modelName, '/Log_Filtered_Echo'], ...
    'Position', [1100, 185, 1170, 215], 'VariableName', 'sim_v_filtered', 'SaveFormat', 'Array');
add_block('simulink/Sinks/To Workspace', [modelName, '/Log_Comparator_Out'], ...
    'Position', [1100, 240, 1170, 270], 'VariableName', 'sim_v_comp', 'SaveFormat', 'Array');

add_line(modelName, '2MHz_Carrier/1', 'Bipolar_Shift/1', 'autorouting', 'on');
add_line(modelName, 'DC_Offset_20V/1', 'Bipolar_Shift/2', 'autorouting', 'on');
add_line(modelName, 'Bipolar_Shift/1', 'MAX14808_Pulser/1', 'autorouting', 'on');
add_line(modelName, '5_Cycle_Gate_2p5us/1', 'MAX14808_Pulser/2', 'autorouting', 'on');
add_line(modelName, 'MAX14808_Pulser/1', 'AirBacked_PZT_2MHz/1', 'autorouting', 'on');
add_line(modelName, 'AirBacked_PZT_2MHz/1', 'TR_Switch_Leakage/1', 'autorouting', 'on');
add_line(modelName, 'AirBacked_PZT_2MHz/1', 'Anterior_Wall_32us/1', 'autorouting', 'on');
add_line(modelName, 'AirBacked_PZT_2MHz/1', 'Posterior_Wall_138us/1', 'autorouting', 'on');
add_line(modelName, 'Anterior_Wall_32us/1', 'Anterior_Atten/1', 'autorouting', 'on');
add_line(modelName, 'Posterior_Wall_138us/1', 'Posterior_Atten/1', 'autorouting', 'on');
add_line(modelName, 'TR_Switch_Leakage/1', 'LVOUT_Node/1', 'autorouting', 'on');
add_line(modelName, 'Anterior_Atten/1', 'LVOUT_Node/2', 'autorouting', 'on');
add_line(modelName, 'Posterior_Atten/1', 'LVOUT_Node/3', 'autorouting', 'on');
add_line(modelName, 'Thermal_Noise/1', 'LVOUT_Node/4', 'autorouting', 'on');
add_line(modelName, 'LVOUT_Node/1', 'OPA357_Amp_Gain10/1', 'autorouting', 'on');
add_line(modelName, 'OPA357_Amp_Gain10/1', 'RC_LPF_5p88MHz/1', 'autorouting', 'on');
add_line(modelName, 'RC_LPF_5p88MHz/1', 'MAX941_Comparator/1', 'autorouting', 'on');
add_line(modelName, 'MAX14808_Pulser/1', 'UBVM_Oscilloscope/1', 'autorouting', 'on');
add_line(modelName, 'RC_LPF_5p88MHz/1', 'UBVM_Oscilloscope/2', 'autorouting', 'on');
add_line(modelName, 'MAX941_Comparator/1', 'UBVM_Oscilloscope/3', 'autorouting', 'on');
add_line(modelName, 'RC_LPF_5p88MHz/1', 'Log_Filtered_Echo/1', 'autorouting', 'on');
add_line(modelName, 'MAX941_Comparator/1', 'Log_Comparator_Out/1', 'autorouting', 'on');

Simulink.BlockDiagram.arrangeSystem(modelName);
save_system(modelName, [modelName, '.slx']);
fprintf('Successfully generated and saved: %s.slx!\n', modelName);
