# Vocabulary exercises

A vocabulary exercise is a coherent text about the content of the materials with the technical
terms missing. The AI writes the text itself, it is not a quote from the material.

![The vocabulary exercises in the workspace](/manual/{lang}/vocabulary-exercise-sets.png)

## Two ways to an exercise

- **From selected sources**: The AI picks the technical terms itself from the ticked materials
- **From a flashcard set**: The terms of a finished set of vocab cards become the gaps. The AI
  still writes the text from the ticked materials, so this way needs ticked materials as well

On top of that you choose 5, 10 or 15 gaps. On the way through vocab cards the text has at most as
many gaps as the set has cards. No instruction can be added here.

How much material is read depends on the number of gaps, just as in the technical language
trainer. Only the way through the materials uses the item stock, from a set of vocab cards every
text is made fresh.

## What is in the text

- **Inflected forms**: askFrancis has at least about a third of the gaps built so that the base form does
  not fit unchanged, for example because of an ending, a plural or a tense. At least one gap takes
  the word unchanged
- **Each term once**: No word appears twice as a gap
- **Fewer gaps than chosen**: askFrancis fills in unusable gaps itself before showing the text. If fewer
  than half are left, the exercise fails

![A vocabulary exercise](/manual/{lang}/vocabulary-exercise.png)

## While solving

The word bank below the text shows all the missing words in their base form, in random order. It
stays visible while scrolling. One click strikes a word through, a second brings it back.

Check works once per round, after that all gaps are locked. Every gap gets a colour:

- **Green**: correct
- **Yellow**: almost correct, for example a typo or a slightly missed ending
- **Red**: wrong

The solution appears next to every yellow and red gap. Below the text it says how many gaps were
fully correct, almost correct ones do not count. Done leads to the summary. Retry wrong there
currently opens the whole text again empty, not just the wrong gaps.

## How it is checked

askFrancis compares every entry with exactly one solution, without an AI call. Capitalisation and
punctuation do not count. Another form that fits just as well is therefore marked almost correct
or wrong.
