# Rebuilding the Caregiver Care Binder

`content.py` holds every page's text: the t4 draft with the compliance review's edits applied.
`build.py` lays out the PDFs, and `images.py` makes the listing images and pins from rendered pages.

The fonts are Inter (SIL Open Font License, commercial use allowed), converted to TTF for ReportLab.

    python otf2ttf.py                                           # makes Inter-*.ttf (needs fonttools)
    python build.py out                                         # both PDFs
    pdftoppm -r 110 -png out/Caregiver-Care-Binder-US-Letter.pdf pages110/p
    python images.py                                            # 5 listing images + 10 pins
