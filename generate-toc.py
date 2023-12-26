'''
<!-- TOC start (generated with https://github.com/derlin/bitdowntoc) -->

- [Overview](#overview)
- [Usage](#usage)
   * [Installation](#installation)
   * [Data preparation](#data-preparation)
      + [CSV file](#csv-file)
      + [Database](#database)
         - [Environment file](#environment-file)
   * [Execution](#execution)
      + [A note about sampling](#a-note-about-sampling)
         - [How to specify sampling](#how-to-specify-sampling)
      + [Examples](#examples)
   * [Results](#results)
      + [score](#score)
      + [employee_id](#employee_id)
- [Potential improvements](#potential-improvements)


- level 1
    * level 2
        + level 3
           - level 4


<!-- TOC end -->

<!-- TOC --><a name="overview"></a>
# Overview
That's what this program does.

<!-- TOC --><a name="usage"></a>
# Usage

<!-- TOC --><a name="installation"></a>
## Installation
- `git clone https://github.com/jsf80238/data_profiling.git`
- `cd data_profiling`
- `python3 -m venv your_dir`
'''

import fileinput
import logging
import re
import sys

logging.basicConfig(level=logging.INFO)

TOC_INDICATOR = "<!-- TOC "
TOC_START_INDICATOR = "<!-- TOC start -->"
TOC_END_INDICATOR = "<!-- TOC end -->"
HEADING_PATTERN = re.compile(r"^(#+)\s+(.+)")
INDENT_WIDTH = 4
ODD_LEVEL_TOC_CHAR = "*"
EVEN_LEVEL_TOC_CHAR = "-"

line_list = [x.rstrip() for x in fileinput.input()]
if line_list[0].startswith(TOC_INDICATOR):
    logging.info("I see existing TOC entries, I will remove them.")
    is_found_toc_end = False
    for line in line_list:
        if line.startswith(TOC_END_INDICATOR):
            is_found_toc_end = True
        if is_found_toc_end:
            if not line.startswith(TOC_INDICATOR):
                print(line)
else:
    logging.info("Will create new TOC entries.")
    print(TOC_START_INDICATOR)
    toc_list = list()
    augmented_content_list = list()
    for line in line_list:
        match = HEADING_PATTERN.search(line)
        if match:
            indent_level = len(match.group(1)) - 1
            heading_name = match.group(2)
            if indent_level % 2 == 0:
                char = EVEN_LEVEL_TOC_CHAR
            else:
                char = ODD_LEVEL_TOC_CHAR
            # - [Overview](#overview)
            anchor = "(#" + heading_name.lower().replace(" ", "-") + ")"  # for example, "(#my-heading)"
            print(" " * indent_level * INDENT_WIDTH + char + " [" + heading_name + "]" + anchor)
            augmented_content_list.append(f'<!-- TOC --><a name="{heading_name.lower()}"></a>')
        augmented_content_list.append(line)
    print(TOC_END_INDICATOR)
    for line in augmented_content_list:
        print(line)
