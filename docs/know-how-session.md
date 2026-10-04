# Know-how session: from PDF certificate to dashboard (45 minutes)

A session outline for a tax team that wants to see what document automation can and cannot do, using this project as the example.

## 1. The problem (5 min)
- Certificates arrive from many paying agents and custodians, each with its own layout, labels and number format.
- Today someone retypes the values, checks the arithmetic and tracks reclaim deadlines in a spreadsheet.
- Question for the room: which step takes the most time, and which mistake hurts the most?

## 2. Live demo (15 min)
1. Drop a certificate into the SharePoint inbox; the Power Automate flow sends it to the API.
2. Show the extracted fields and the checks: totals, rate times gross, duplicate IDs, currency, dates.
3. Show a reclaim finding: rate withheld vs treaty rate, amount, deadline.
4. Open the Power BI report: clean rate, tax withheld by country, reclaims by deadline, filing calendar.

## 3. How it works, without code (10 min)
- Extraction: label synonyms per layout (local) or Azure AI Document Intelligence for scanned or unusual documents.
- Rules live in one YAML file that the tax team can read and change: rates, reclaim periods, tolerances.
- Generative AI is used only to word the weekly digest, and its text is rejected if it contains a number that is not in the facts.

## 4. Limits and controls (5 min)
- Treaty rates and reclaim periods in the demo are illustrative; the tax team owns the real values.
- Every finding keeps the source file name, so a person can always check the original.
- Unreadable values are reported, never guessed.

## 5. Ideation (10 min)
- Which other recurring documents could go through the same flow (fund statements, capital calls, tax residency certificates)?
- Which check would save the team the most time next quarter?
- Pick one idea for a two-week proof of concept.
