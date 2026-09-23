"""What a field reference looks like in a Tableau formula.

One definition, because three places have to agree on it and they answer
questions that are only consistent if they see the same references:

* `grain` decides what an expression evaluates at, by looking at every
  reference and whether it sits inside an aggregation;
* `translator` rewrites each reference into DAX;
* `graph` resolves each reference to the field it points at, to know what a
  calculation depends on.

If the graph saw a reference the translator did not, it would claim a
dependency that the emitted DAX does not have, and refuse a calculation for
reading something it never read. Two copies of a regex are two chances to drift
apart, and this one was already copied once.

`[Field]`, or `[datasource].[Field]` - the qualifier is matched and discarded,
because the group is the field name.
"""

from __future__ import annotations

import re

REF_RE = re.compile(r"(?:\[[^\[\]]+\]\.)?\[([^\[\]]+)\]")
