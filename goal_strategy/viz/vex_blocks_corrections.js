// Corrections applied OVER defineVexBlocks() — same approach as the reference
// renderer (goal_strategy_detection/scripts/build_sample.py), which deliberately
// overwrites the upstream definitions: the corpus XML carries free parameters as
// <value> inputs holding math_number shadows, so definitions must declare
// input_value sockets (not field_number fields) or Blockly silently drops the
// authored value and renders the default. Field/input/statement names below are
// validated against the corpus XML census by tests/test_viz_data.py.
const VEX_BLOCK_CORRECTIONS = /*JSON-START*/[
  {"type": "pg_drivetrain_drive_for",
   "message0": "drive %1 for %2 %3",
   "args0": [
     {"type": "field_dropdown", "name": "DIRECTION",
      "options": [["forward", "fwd"], ["reverse", "rev"]]},
     {"type": "input_value", "name": "AMOUNT"},
     {"type": "field_dropdown", "name": "UNITS",
      "options": [["mm", "mm"], ["cm", "cm"], ["in", "in"]]}],
   "inputsInline": true, "colour": 230,
   "previousStatement": null, "nextStatement": null},

  {"type": "pg_drivetrain_turn_for",
   "message0": "turn %1 for %2 degrees",
   "args0": [
     {"type": "field_dropdown", "name": "TURNDIRECTION",
      "options": [["left", "left"], ["right", "right"]]},
     {"type": "input_value", "name": "AMOUNT"}],
   "inputsInline": true, "colour": 230,
   "previousStatement": null, "nextStatement": null},

  {"type": "pg_drivetrain_turn_to_heading",
   "message0": "turn to heading %1 degrees",
   "args0": [{"type": "input_value", "name": "HEADING"}],
   "inputsInline": true, "colour": 230,
   "previousStatement": null, "nextStatement": null},

  {"type": "pg_drivetrain_turn_to_rotation",
   "message0": "turn to rotation %1 degrees",
   "args0": [{"type": "input_value", "name": "ROTATION"}],
   "inputsInline": true, "colour": 230,
   "previousStatement": null, "nextStatement": null},

  {"type": "pg_drivetrain_set_drive_velocity",
   "message0": "set drive velocity to %1 %2",
   "args0": [
     {"type": "input_value", "name": "VELOCITY"},
     {"type": "field_dropdown", "name": "UNITS",
      "options": [["%", "pct"], ["mm/s", "mm/s"]]}],
   "inputsInline": true, "colour": 230,
   "previousStatement": null, "nextStatement": null},

  {"type": "pg_drivetrain_set_turn_velocity",
   "message0": "set turn velocity to %1 %2",
   "args0": [
     {"type": "input_value", "name": "VELOCITY"},
     {"type": "field_dropdown", "name": "UNITS",
      "options": [["%", "pct"], ["deg/s", "deg/s"]]}],
   "inputsInline": true, "colour": 230,
   "previousStatement": null, "nextStatement": null},

  {"type": "pg_control_wait_until",
   "message0": "wait until %1",
   "args0": [{"type": "input_value", "name": "CONDITION"}],
   "inputsInline": true, "colour": 60,
   "previousStatement": null, "nextStatement": null},

  {"type": "pg_control_if_then",
   "message0": "if %1 then %2",
   "args0": [
     {"type": "input_value", "name": "CONDITION"},
     {"type": "input_statement", "name": "SUBSTACK"}],
   "colour": 60, "previousStatement": null, "nextStatement": null},

  {"type": "pg_control_if_then_else",
   "message0": "if %1 then %2 else %3",
   "args0": [
     {"type": "input_value", "name": "CONDITION"},
     {"type": "input_statement", "name": "SUBSTACK"},
     {"type": "input_statement", "name": "SUBSTACK2"}],
   "colour": 60, "previousStatement": null, "nextStatement": null},

  {"type": "pg_control_if_elseif_else",
   "message0": "if %1 then %2 else if %3 then %4 else %5",
   "args0": [
     {"type": "input_value", "name": "CONDITION1"},
     {"type": "input_statement", "name": "SUBSTACK1"},
     {"type": "input_value", "name": "CONDITION2"},
     {"type": "input_statement", "name": "SUBSTACK2"},
     {"type": "input_statement", "name": "SUBSTACK_ELSE"}],
   "colour": 60, "previousStatement": null, "nextStatement": null},

  {"type": "pg_control_repeat_until",
   "message0": "repeat until %1 %2",
   "args0": [
     {"type": "input_value", "name": "CONDITION"},
     {"type": "input_statement", "name": "SUBSTACK"}],
   "colour": 60, "previousStatement": null, "nextStatement": null},

  {"type": "pg_control_while",
   "message0": "while %1 %2",
   "args0": [
     {"type": "input_value", "name": "CONDITION"},
     {"type": "input_statement", "name": "SUBSTACK"}],
   "colour": 60, "previousStatement": null, "nextStatement": null},

  {"type": "pg_events_broadcast",
   "message0": "broadcast %1",
   "args0": [{"type": "field_input", "name": "BROADCAST_OPTION", "text": ""}],
   "colour": 45, "previousStatement": null, "nextStatement": null},

  {"type": "pg_events_broadcast_and_wait",
   "message0": "broadcast %1 and wait",
   "args0": [{"type": "field_input", "name": "BROADCAST_OPTION", "text": ""}],
   "colour": 45, "previousStatement": null, "nextStatement": null},

  {"type": "pg_events_when_broadcasted",
   "message0": "when I receive %1",
   "args0": [{"type": "field_input", "name": "BROADCAST_OPTION", "text": ""}],
   "colour": 45, "nextStatement": null},

  {"type": "pg_events_when_bumper",
   "message0": "when %1 %2",
   "args0": [
     {"type": "field_label_serializable", "name": "BUMPER", "text": "bumper"},
     {"type": "field_label_serializable", "name": "EVENTTYPE", "text": "pressed"}],
   "colour": 45, "nextStatement": null},

  {"type": "pg_events_optical_detect_object",
   "message0": "when %1 %2 object",
   "args0": [
     {"type": "field_label_serializable", "name": "OPTICAL", "text": "eye"},
     {"type": "field_label_serializable", "name": "OPTIONS", "text": "detects"}],
   "colour": 45, "nextStatement": null},

  {"type": "pg_magnet_set_magnet_state",
   "message0": "set %1 to %2",
   "args0": [
     {"type": "field_label_serializable", "name": "MAGNET", "text": "Magnet"},
     {"type": "field_label_serializable", "name": "ACTION", "text": "boost"}],
   "colour": 290, "previousStatement": null, "nextStatement": null},

  {"type": "pg_operator_math",
   "message0": "%1 %2 %3",
   "args0": [
     {"type": "input_value", "name": "NUM1"},
     {"type": "field_label_serializable", "name": "MATH", "text": "+"},
     {"type": "input_value", "name": "NUM2"}],
   "inputsInline": true, "output": "Number", "colour": 195},

  {"type": "pg_operator_random",
   "message0": "random number between %1 and %2",
   "args0": [
     {"type": "input_value", "name": "FROM"},
     {"type": "input_value", "name": "TO"}],
   "inputsInline": true, "output": "Number", "colour": 195},

  {"type": "pg_variables_set_variable",
   "message0": "set %1 to %2",
   "args0": [
     {"type": "field_input", "name": "VARIABLE", "text": "variable"},
     {"type": "input_value", "name": "VALUE"}],
   "inputsInline": true, "colour": 330,
   "previousStatement": null, "nextStatement": null},

  {"type": "pg_variables_change_variable",
   "message0": "change %1 by %2",
   "args0": [
     {"type": "field_input", "name": "VARIABLE", "text": "variable"},
     {"type": "input_value", "name": "VALUE"}],
   "inputsInline": true, "colour": 330,
   "previousStatement": null, "nextStatement": null},

  {"type": "pg_variables_variable",
   "message0": "%1",
   "args0": [{"type": "field_input", "name": "VARIABLE", "text": "variable"}],
   "output": null, "colour": 330},

  {"type": "pg_sensing_optical_color",
   "message0": "%1 detects %2 ?",
   "args0": [
     {"type": "field_label_serializable", "name": "OPTICAL", "text": "eye"},
     {"type": "field_label_serializable", "name": "COLORS", "text": "color"}],
   "output": "Boolean", "colour": 65},

  {"type": "pg_sensing_optical_near_object",
   "message0": "%1 near object?",
   "args0": [{"type": "field_label_serializable", "name": "OPTICAL", "text": "eye"}],
   "output": "Boolean", "colour": 65},

  {"type": "pg_sensing_distance_found",
   "message0": "%1 found object?",
   "args0": [{"type": "field_label_serializable", "name": "DISTANCE", "text": "distance"}],
   "output": "Boolean", "colour": 65},

  {"type": "pg_sensing_distance_distance",
   "message0": "%1 distance in %2",
   "args0": [
     {"type": "field_label_serializable", "name": "DISTANCE", "text": "distance"},
     {"type": "field_label_serializable", "name": "UNITS", "text": "mm"}],
   "output": "Number", "colour": 65}
]/*JSON-END*/;

function defineVexBlockCorrections() {
  for (const def of VEX_BLOCK_CORRECTIONS) {
    delete Blockly.Blocks[def.type];   // silence overwrite warnings
  }
  Blockly.defineBlocksWithJsonArray(VEX_BLOCK_CORRECTIONS);
}
