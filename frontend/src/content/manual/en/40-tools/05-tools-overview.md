# The services at a glance

The start page shows every service as a tile with one sentence on what it does. The group carries
the tag Teachers, it is aimed at teaching staff.

![The start page with the tiles](/manual/{lang}/start-page.png)

- **Translation** translates texts and documents between German and English and keeps the layout
- **Text to audio** reads texts and documents aloud
- **Audio to text** writes audio and video down
- **Report** brings several sources together into one text
- **Pages** turns material into a learning page you can edit and share
- **Screencast** turns slides into a narrated video
- **Podcast** turns material into a conversation to listen to
- **Presentation** turns material into a PowerPoint file in the university's design
- **Image generation** creates, edits and describes images
- **Interpreter** translates a conversation between two languages as it happens
- **Glossary** keeps term lists for translations

Anyone with a single destination only, such as students with just the learning assistant, lands there
directly and never sees the tile page. The askFrancis logo in the top left always leads back to the
start page.

## Who sees which services

Every service is a right of its own in the permissions matrix, named like its tile. On top of
that the administration can release or lock each service for everyone. If a tile is missing, one
of the two is the reason.

## Files or workspace

Most services work with an uploaded file: in, result, download. Report, podcast, presentation
and the additional material of the screencast also have a Workspace tab. There you pick fully
processed sources from one of your workspaces without uploading them again. The tab only appears
when you may use the learning assistant.

## Jobs and quota

Long jobs run in the background. You can leave the page, the result waits under **Jobs** in the
header.

- **Quota**: out of the box 100 jobs per service in 4 hours. The presentation has none.
  Interpreter and glossary create no jobs and count nowhere.
- **Open jobs**: at most 5 at once per person. Services with a voice, that is text to audio,
  podcast and screencast, count apart from the rest, so a running voicing never blocks a
  translation. Beyond that the service says: Too many of your jobs are running. Wait until one is
  finished.
- **Both numbers** are changed by the administration under Limits.

## Material for report, podcast and presentation

The three services and the additional material of the screencast take the same material with the
same limits:

- **Amount**: up to 10 files or workspace sources per job, as PDF, Word, PowerPoint, text or
  Markdown. The report also takes subtitles as SRT and VTT.
- **Per file**: 500 MB and 200 pages, both set by the administration.
- **Together**: 500,000 characters across all files, fixed in the code. A counter on the page
  shows while you pick how much of it is used. If it is too much, the start stays locked until
  you take something out.
- **Text layer**: only text is read. Scanned pages without text stay empty, a file with no text
  at all is refused.

## The optional instruction

Report, podcast and presentation have an Instruction field. It stays empty when you want nothing
special. The AI reads the instruction next to the material and sorts it:

- **A topic** narrows down: only chapter 2 plans everything around what the material says on it
  and leaves the rest out, even whole files.
- **A wish about the manner** only shapes the text: for first-year students, short, with
  examples. The content stays that of the material, nothing is added.
- **A topic the material does not cover** drops out. Podcast and presentation say so with a
  notice and use all of the material, the report does it silently.
- **Nonsense** or a request to leave the material drops out silently.

After 500 characters the instruction is cut off.

## AI notice in the results

What the services produce carries a notice that it was created with AI, as far as the format
allows:

- **MP3** from text to audio and podcast: in the file information, nothing is audible
- **Video** from the screencast: a notice slide at the beginning and at the end
- **Images**: in the image information of the PNG file
- **Subtitles as VTT**: a note line that no player shows
- **Report**: a line below the title, in Markdown as in Word
- **Presentation**: AI generated in the bottom right of every slide

Translated documents, subtitles as SRT, the transcript of a podcast and the transcript of the
interpreter stay without a notice.
