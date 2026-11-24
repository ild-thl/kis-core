# My jobs

Every order given to a service is a job. The job list shows what is running, what is finished and
what went wrong.

![The job list](/manual/{lang}/my-jobs.png)

## Where it is

Through **Jobs** in the header. The red dot next to it means: since you last opened the list, a
job has finished or failed.

## What you do there

- **Filter** by service, period or search term.
- **Download**: the result, for a report also the Word file. If a job has several sources, the
  file list folds open below the name.
- **Open**: podcast, presentation and screencast lead back into their service, an interrupted
  screencast can be resumed from there.
- **Retry** or delete what failed.

## States

- **Pending** and **Queued**: the job is accepted and not yet on
- **Running**: work is being done
- **Retrying**: the job waits briefly and tries again by itself
- **Paused**: after several failed attempts the job waits for **Continue**
- **Resume**: the job waits for input from you, for example in the screencast
- **Done**, **Failed** and **Expired**: with Expired the job was done, but the result file is no
  longer there

## What happens on a failure

Long jobs work in stages and save their progress. If a piece fails, askFrancis makes up to 3 new
attempts by itself, after 1 minute, 3 minutes and 10 minutes. Then the job stands on Paused and
names the last error. Continue picks up where it stopped, finished parts stay.

An overloaded AI provider does not count as a failure. The job waits 1 to 3 minutes and tries
again, for up to 12 hours, without using up an attempt.

This applies to text to audio, report, screencast, podcast and presentation. In the podcast and
the presentation only the voicing and the slide build keep their finished parts, script and
outline start over on a failure. Translation, audio to text and image generation know no pausing,
there it says Failed right away and you retry.

A job that lies paused or waiting for 7 days is given up.

## The list is limited

Out of the box the last 100 jobs per person are kept. When a new one arrives, the oldest drops
out, together with its result. There is no deadline. The administration can change the number,
also to unlimited.
