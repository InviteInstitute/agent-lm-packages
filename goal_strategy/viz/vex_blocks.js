/* -----------------------------
   Simple stub definitions for common VEX blocks
------------------------------*/
function defineVexBlocks() {
  Blockly.defineBlocksWithJsonArray([
    // Stub for pg_drivetrain_go_to_object block
    {
      "type": "pg_drivetrain_go_to_object",
      "message0": "go to %1",
      "args0": [
        { "type": "field_dropdown", "name": "OBJECT", "options": [["minerals","minerals"],["enemy","enemy"],["base","base"]] }
      ],
      "colour": 230,
      "previousStatement": null,
      "nextStatement": null
    },
    // Stub for pg_control_stop_project block
    {
      "type": "pg_control_stop_project",
      "message0": "stop project",
      "colour": 60,
      "previousStatement": null,
      "nextStatement": null
    },
    // Stub for math_number block used in value changes
    {
      "type": "math_number",
      "message0": "%1",
      "args0": [
        { "type": "field_number", "name": "NUM", "value": 0 }
      ],
      "output": "Number",
      "colour": 230
    },
    // Stub for math_positive_number shadow block used in wait blocks
    {
      "type": "math_positive_number",
      "message0": "%1",
      "args0": [
        { "type": "field_number", "name": "NUM", "value": 1, "min": 0 }
      ],
      "output": "Number",
      "colour": 230
    },
    // Stub for pg_looks_clear_all_rows block
    {
      "type": "pg_looks_clear_all_rows",
      "message0": "clear all rows",
      "colour": 160,
      "previousStatement": null,
      "nextStatement": null
    },
    // Stub for pg_other_comment block used in some projects
    {
      "type": "pg_other_comment",
      "message0": "%1",
      "args0": [
        { "type": "field_input", "name": "COMMENT", "text": "" }
      ],
      "colour": 60,
      "previousStatement": null,
      "nextStatement": null
    },
    // Stub for math_whole_number shadow block used in repeat blocks
    {
      "type": "math_whole_number",
      "message0": "%1",
      "args0": [
        { "type": "field_number", "name": "NUM", "value": 1 }
      ],
      "output": "Number",
      "colour": 230
    },
    // Stub for comment_multiline block used in example projects
    {
      "type": "comment_multiline",
      "message0": "%1",
      "args0": [
        { "type": "field_input", "name": "COMMENT", "text": "" }
      ],
      "colour": 60,
      "previousStatement": null,
      "nextStatement": null
    },
    // === EVENTS ===
    {
      "type": "pg_events_when_started",
      "message0": "when started",
      "colour": 120,
      "nextStatement": null,
      "hat": "cap"
    },
    {
      "type": "pg_events_broadcast",
      "message0": "broadcast %1",
      "args0": [{ "type": "field_input", "name": "MSG", "text": "message" }],
      "colour": 120,
      "previousStatement": null,
      "nextStatement": null
    },
    {
      "type": "pg_events_when_broadcasted",
      "message0": "when I receive %1",
      "args0": [{ "type": "field_input", "name": "MSG", "text": "message" }],
      "colour": 120,
      "nextStatement": null,
      "hat": "cap"
    },
    {
      "type": "pg_events_when_bumper",
      "message0": "when bumper pressed",
      "colour": 120,
      "nextStatement": null,
      "hat": "cap"
    },
    {
      "type": "pg_events_when_timer",
      "message0": "when timer %1 seconds",
      "args0": [{ "type": "field_number", "name": "TIME", "value": 1 }],
      "colour": 120,
      "nextStatement": null,
      "hat": "cap"
    },
    {
      "type": "pg_events_optical_detect_object",
      "message0": "when optical sensor detects object",
      "colour": 120,
      "nextStatement": null,
      "hat": "cap"
    },

    // === CONTROL ===
    {
      "type": "pg_control_wait",
      "message0": "wait %1 seconds",
      "args0": [{ "type": "input_value", "name": "DURATION" }],
      "colour": 60,
      "previousStatement": null,
      "nextStatement": null
    },
    {
      "type": "pg_control_repeat",
      "message0": "repeat %1 times %2",
      "args0": [
        { "type": "input_value", "name": "TIMES" },
        { "type": "input_statement", "name": "SUBSTACK" }
      ],
      "colour": 60,
      "previousStatement": null,
      "nextStatement": null
    },
    {
      "type": "pg_control_repeat_until",
      "message0": "repeat until %1 %2",
      "args0": [
        { "type": "input_value", "name": "CONDITION", "check": "Boolean" },
        { "type": "input_statement", "name": "DO" }
      ],
      "colour": 60,
      "previousStatement": null,
      "nextStatement": null
    },
    {
      "type": "pg_control_forever",
      "message0": "forever %1",
      "args0": [{ "type": "input_statement", "name": "SUBSTACK" }],
      "colour": 60,
      "previousStatement": null,
      "nextStatement": null
    },
    {
      "type": "pg_control_if_then",
      "message0": "if %1 then %2",
      "args0": [
        { "type": "input_value", "name": "CONDITION", "check": "Boolean" },
        { "type": "input_statement", "name": "DO" }
      ],
      "colour": 60,
      "previousStatement": null,
      "nextStatement": null
    },
    {
      "type": "pg_control_if_then_else",
      "message0": "if %1 then %2 else %3",
      "args0": [
        { "type": "input_value", "name": "CONDITION", "check": "Boolean" },
        { "type": "input_statement", "name": "DO" },
        { "type": "input_statement", "name": "ELSE" }
      ],
      "colour": 60,
      "previousStatement": null,
      "nextStatement": null
    },
    {
      "type": "pg_control_if_elseif_else",
      "message0": "if %1 then %2 else if %3 then %4 else %5",
      "args0": [
        { "type": "input_value", "name": "COND1", "check": "Boolean" },
        { "type": "input_statement", "name": "DO1" },
        { "type": "input_value", "name": "COND2", "check": "Boolean" },
        { "type": "input_statement", "name": "DO2" },
        { "type": "input_statement", "name": "ELSE" }
      ],
      "colour": 60,
      "previousStatement": null,
      "nextStatement": null
    },
    {
      "type": "pg_control_while",
      "message0": "while %1 %2",
      "args0": [
        { "type": "input_value", "name": "CONDITION", "check": "Boolean" },
        { "type": "input_statement", "name": "DO" }
      ],
      "colour": 60,
      "previousStatement": null,
      "nextStatement": null
    },
    {
      "type": "pg_control_break",
      "message0": "break loop",
      "colour": 60,
      "previousStatement": null,
      "nextStatement": null
    },

    // === DRIVE / ACTIONS ===
    {
      "type": "pg_drivetrain_drive",
      "message0": "drive %1",
      "args0": [{ "type": "field_dropdown", "name": "DIRECTION", "options": [["forward","fwd"],["reverse","rev"]] }],
      "colour": 230,
      "previousStatement": null,
      "nextStatement": null
    },
    {
      "type": "pg_drivetrain_drive_for",
      "message0": "drive %1 for %2 %3",
      "args0": [
        { "type": "field_dropdown", "name": "DIRECTION", "options": [["forward","fwd"],["reverse","rev"]] },
        { "type": "field_number", "name": "AMOUNT", "value": 200 },
        { "type": "field_dropdown", "name": "UNITS", "options": [["mm","mm"],["cm","cm"],["in","in"]] }
      ],
      "colour": 230,
      "previousStatement": null,
      "nextStatement": null
    },
    {
      "type": "pg_drivetrain_turn_for",
      "message0": "turn %1 for %2 degrees",
      "args0": [
        { "type": "field_dropdown", "name": "TURNDIRECTION", "options": [["left","left"],["right","right"]] },
        { "type": "field_number", "name": "AMOUNT", "value": 90 }
      ],
      "colour": 230,
      "previousStatement": null,
      "nextStatement": null
    },
    {
      "type": "pg_drivetrain_turn",
      "message0": "turn %1",
      "args0": [{ "type": "field_dropdown", "name": "TURNDIRECTION", "options": [["left","left"],["right","right"]] }],
      "colour": 230,
      "previousStatement": null,
      "nextStatement": null
    },
    {
      "type": "pg_drivetrain_stop_driving",
      "message0": "stop driving",
      "colour": 230,
      "previousStatement": null,
      "nextStatement": null
    },
    {
      "type": "pg_drivetrain_turn_to_heading",
      "message0": "turn to heading %1°",
      "args0": [{ "type": "field_number", "name": "HEADING", "value": 0 }],
      "colour": 230,
      "previousStatement": null,
      "nextStatement": null
    },
    {
      "type": "pg_drivetrain_turn_to_rotation",
      "message0": "turn to rotation %1°",
      "args0": [{ "type": "field_number", "name": "ROTATION", "value": 0 }],
      "colour": 230,
      "previousStatement": null,
      "nextStatement": null
    },
    {
      "type": "pg_drivetrain_set_drive_velocity",
      "message0": "set drive velocity to %1 %2",
      "args0": [
        { "type": "field_number", "name": "SPEED", "value": 50 },
        { "type": "field_dropdown", "name": "UNITS", "options": [["%","pct"],["mm/s","mm/s"]] }
      ],
      "colour": 230,
      "previousStatement": null,
      "nextStatement": null
    },
    {
      "type": "pg_drivetrain_set_turn_velocity",
      "message0": "set turn velocity to %1 %2",
      "args0": [
        { "type": "field_number", "name": "SPEED", "value": 50 },
        { "type": "field_dropdown", "name": "UNITS", "options": [["%","pct"],["deg/s","deg/s"]] }
      ],
      "colour": 230,
      "previousStatement": null,
      "nextStatement": null
    },
    {
      "type": "pg_drivetrain_set_drive_timeout",
      "message0": "set drive timeout to %1 seconds",
      "args0": [{ "type": "field_number", "name": "TIMEOUT", "value": 3 }],
      "colour": 230,
      "previousStatement": null,
      "nextStatement": null
    },

    // === LOOKS ===
    {
      "type": "pg_looks_fill_color_plus",
      "message0": "fill color %1",
      "args0": [{ "type": "field_colour", "name": "COLOR", "colour": "#ff0000" }],
      "colour": 20,
      "previousStatement": null,
      "nextStatement": null
    },
    {
      "type": "pg_looks_set_pen_color_plus",
      "message0": "set pen color to %1",
      "args0": [{ "type": "field_colour", "name": "COLOR", "colour": "#0000ff" }],
      "colour": 20,
      "previousStatement": null,
      "nextStatement": null
    },
    {
      "type": "pg_looks_set_pen_width",
      "message0": "set pen width to %1",
      "args0": [{ "type": "field_number", "name": "WIDTH", "value": 1 }],
      "colour": 20,
      "previousStatement": null,
      "nextStatement": null
    },
    {
      "type": "pg_looks_move_pen",
      "message0": "move pen %1",
      "args0": [{ "type": "field_dropdown", "name": "ACTION", "options": [["up","up"],["down","down"]] }],
      "colour": 20,
      "previousStatement": null,
      "nextStatement": null
    },
    {
      "type": "pg_looks_print",
      "message0": "print %1",
      "args0": [{ "type": "input_value", "name": "TEXT" }],
      "colour": 20,
      "previousStatement": null,
      "nextStatement": null
    },
    {
      "type": "pg_looks_set_print_color",
      "message0": "set print color to %1",
      "args0": [{ "type": "field_colour", "name": "COLOR", "colour": "#000000" }],
      "colour": 20,
      "previousStatement": null,
      "nextStatement": null
    },

    // === SENSING / AI ===
    {
      "type": "pg_sensing_reset_timer",
      "message0": "reset timer",
      "colour": 65,
      "previousStatement": null,
      "nextStatement": null
    },
    {
      "type": "pg_sensing_timer_value",
      "message0": "timer value",
      "output": "Number",
      "colour": 65
    },
    {
      "type": "pg_sensing_optical_color",
      "message0": "optical color",
      "output": "Colour",
      "colour": 65
    },
    {
      "type": "pg_sensing_bumper",
      "message0": "bumper pressed?",
      "output": "Boolean",
      "colour": 65
    },
    {
      "type": "pg_sensing_distance_found",
      "message0": "object detected?",
      "output": "Boolean",
      "colour": 65
    },
    {
      "type": "pg_sensing_ai_sees",
      "message0": "AI sees %1",
      "args0": [{ "type": "field_input", "name": "OBJECT", "text": "target" }],
      "output": "Boolean",
      "colour": 65
    },
    {
      "type": "pg_sensing_position",
      "message0": "robot position",
      "output": "Number",
      "colour": 65
    },
    {
      "type": "pg_sensing_ai_smells",
      "message0": "AI smells %1",
      "args0": [{ "type": "field_input", "name": "THING", "text": "object" }],
      "output": "Boolean",
      "colour": 65
    },

    // === VARIABLES ===
    {
      "type": "pg_variables_set_variable",
      "message0": "set variable %1 to %2",
      "args0": [
        { "type": "field_variable", "name": "VAR", "variable": "item" },
        { "type": "input_value", "name": "VALUE" }
      ],
      "colour": 330,
      "previousStatement": null,
      "nextStatement": null
    },

    // === OPERATORS ===
    {
      "type": "pg_operator_random",
      "message0": "random number between %1 and %2",
      "args0": [
        { "type": "field_number", "name": "MIN", "value": 1 },
        { "type": "field_number", "name": "MAX", "value": 10 }
      ],
      "output": "Number",
      "colour": 195
    },
    {
      "type": "pg_operator_not",
      "message0": "not %1",
      "args0": [{ "type": "input_value", "name": "BOOL", "check": "Boolean" }],
      "output": "Boolean",
      "colour": 195
    },

    // === ACTIONS ===
    {
      "type": "pg_actions_interact_with_enemy",
      "message0": "interact with enemy",
      "colour": 290,
      "previousStatement": null,
      "nextStatement": null
    },
    {
      "type": "pg_actions_interact_with_minerals",
      "message0": "interact with minerals",
      "colour": 290,
      "previousStatement": null,
      "nextStatement": null
    },

    // === MISC ===
    {
      "type": "pg_mixed_multiline_command",
      "message0": "do multiline command",
      "colour": 10,
      "previousStatement": null,
      "nextStatement": null
    },
  ]);

  // Blocks present in the tracing corpus but absent from the EventViewer list
  Blockly.defineBlocksWithJsonArray([
    {
      "type": "aim_other_comment",
      "message0": "comment %1",
      "args0": [{ "type": "input_value", "name": "COMMENT" }],
      "colour": 10,
      "previousStatement": null,
      "nextStatement": null
    },
    {
      "type": "comment_text",
      "message0": "%1",
      "args0": [{ "type": "field_input", "name": "comment", "text": "" }],
      "colour": 10,
      "output": null
    },
    {
      "type": "math_number_string",
      "message0": "%1",
      "args0": [{ "type": "field_input", "name": "NUM", "text": "0" }],
      "colour": 230,
      "output": null
    }
  ]);

  // Scratch-style procedure blocks: the label carries proccode from the mutation
  const procMutation = {
    domToMutation: function(xmlElement) {
      const field = this.getField("PROCCODE");
      if (field) field.setValue(xmlElement.getAttribute("proccode") || "");
    },
    mutationToDom: function() {
      return Blockly.utils.xml.createElement("mutation");
    }
  };
  Blockly.Blocks["procedures_definition"] = {
    init: function() {
      this.appendStatementInput("custom_block").appendField("define");
      this.setColour(290);
      this.setNextStatement(true);
    }
  };
  Blockly.Blocks["procedures_prototype"] = Object.assign({
    init: function() {
      this.appendDummyInput().appendField("", "PROCCODE");
      this.setColour(290);
      this.setPreviousStatement(true);
    }
  }, procMutation);
  Blockly.Blocks["procedures_call"] = Object.assign({
    init: function() {
      this.appendDummyInput().appendField("call").appendField("", "PROCCODE");
      this.setColour(290);
      this.setPreviousStatement(true);
      this.setNextStatement(true);
    }
  }, procMutation);

}

// Auto-stub fallback for any remaining unknown types. Called with the parsed
// workspace DOM before Blockly.Xml.domToWorkspace — patching domToBlockHeadless
// does NOT work with the minified CDN build (internal calls bypass the export).
// Shape follows the XML context: a block nested in a <value> needs an output
// connection; anything else gets statement connections. A shape mismatch makes
// Blockly throw on connect, which kills the whole render.
function stubUnknownBlocks(dom) {
  dom.querySelectorAll("block[type], shadow[type]").forEach(function(node) {
    const type = node.getAttribute("type");
    if (!type || Blockly.Blocks[type]) return;
    const parent = node.parentNode;
    const inValue = !!(parent && parent.nodeName && parent.nodeName.toLowerCase() === "value");
    Blockly.Blocks[type] = {
      init: function() {
        this.appendDummyInput().appendField(type);
        this.setColour(200);
        if (inValue) {
          this.setOutput(true);
        } else {
          this.setPreviousStatement(true);
          this.setNextStatement(true);
        }
      }
    };
    console.warn(`Auto-stubbed unknown block: ${type} (${inValue ? "value" : "statement"} shape)`);
  });
}
