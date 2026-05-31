import pysubs2

jp = pysubs2.load("output/subtitles.jp.srt")
fr = pysubs2.load("output/subtitles.fr.srt")

subs = pysubs2.SSAFile()

# Style FR (bas)
subs.styles["FR"] = pysubs2.SSAStyle(
    fontname="Noto Sans",
    fontsize=44,
    primarycolor="&H00FFFFCC",
    outlinecolor="&H00000000",
    borderstyle=1,
    outline=3,
    shadow=1,
    alignment=2  # bas
)

# Style JP (haut)
subs.styles["JP"] = pysubs2.SSAStyle(
    fontname="Noto Sans CJK JP",
    fontsize=30,
    primarycolor="&H00FFFFFF",
    outlinecolor="&H00000000",
    borderstyle=1,
    outline=2,
    shadow=1,
    alignment=8  # haut
)

# Ajouter JP
for line in jp:
    event = pysubs2.SSAEvent(
        start=line.start,
        end=line.end,
        text=line.text,
        style="JP"
    )
    subs.events.append(event)

# Ajouter FR
for line in fr:
    event = pysubs2.SSAEvent(
        start=line.start,
        end=line.end,
        text=line.text,
        style="FR"
    )
    subs.events.append(event)

subs.save("output/dual.ass")
print("✔ dual.ass créé")
