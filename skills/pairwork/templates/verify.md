# Request: check this against its constraints before it ships

{sole_reviewer}

This work is finished and about to go out. Your job is narrow and concrete:
take each constraint below and rule on whether the work actually honours it.

You have not been told whether anyone thinks it passes. Rule on the evidence in
front of you.

## The work

{subject}

## Where to look

{context}

## The constraints it must honour

{constraints}

For every constraint, answer one of:

- **holds** - and name the file and line that makes it hold
- **broken** - and name the file and line where it breaks
- **cannot tell from here** - and say exactly what you would need

"Cannot tell from here" is a real answer and an important one. A constraint
that cannot be checked before the thing ships is itself worth knowing about, and
guessing at it is how a verification pass becomes decoration.

## Anything else

{question}

Beyond the constraints, flag anything that would stop you shipping this - but
keep it separate from the constraint rulings above, and keep it short.

{output_contract}
