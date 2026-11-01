# Sector-score back-test — status 2 Nov 2026 (honest: NOT yet done)

Goal: rebuild sector scores as of past dates (3-5 years) from archived RBI sectoral credit, IIP NIC-2 and exports, and test them against
the later change in RBI FSR sub-sector GNPA and rating-agency downgrade rates; set the OK/Avoid cut-offs from that evidence.

## What was retrievable this run
- RBI FSR sub-sector GNPA (official): parsed for Mar-24 (FSR Jun-2024), Mar-25, Sep-25, Mar-26. Mar-24 added to the engine.
- FSR Jun-2022, Dec-2022, Jun-2023, Dec-2023 PDFs were downloaded but the sub-sector GNPA chart in those editions has a different layout,
  so the parser could not read the labels. Not used; no values typed in by hand.
- Historical IIP NIC-2 and SIBC sector credit as of past dates were NOT rebuilt (needs MoSPI / RBI archive files per month).
- Rating-agency downgrade data: no structured free source wired in.

## Result
- Usable history = 4 GNPA points (2 years) per FSR category. That is too short to compute a hit rate or calibrate cut-offs.
- OK >= 65 / Avoid < 45 remain expert settings, labelled "not back-tested".

## Next steps to make it real
1. Write an FSR parser for the 2021-2023 chart layout (or read the data tables in the FSR statistical annex).
2. Pull monthly SIBC (RBI) and IIP NIC-2 (MoSPI) archives for Mar-2021 onward; replay `score_sector` as of each March.
3. Hit test: Avoid sectors should show a higher 12-month GNPA rise than OK sectors; choose cut-offs that maximise separation.
