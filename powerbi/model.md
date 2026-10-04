# Power BI model

Load every CSV in `out/powerbi/` with *Get data > Text/CSV* (or a folder query in Power Query), set `dim_date[date]` and `fact_certificate[payment_date]` to the Date type, mark `dim_date` as the date table, and paste the measures from `measures.dax`.

## Relationships (star schema)

| From | To | Cardinality |
|---|---|---|
| `fact_certificate[payment_date]` | `dim_date[date]` | many to one |
| `fact_certificate[fund_entity]` | `dim_entity[fund_entity]` | many to one |
| `fact_finding[file_name]` | `fact_certificate[file_name]` | many to one |
| `fact_obligation[fund_entity]` | `dim_entity[fund_entity]` | many to one |

`dim_country` holds statutory and treaty rates per source and residence country and is used as a lookup table on the rates page.

## Report pages

1. **Overview** - cards: Certificates, Clean Rate %, Tax Withheld EUR, Reclaim Potential EUR; bar chart of Tax Withheld EUR by source country; slicer on fund entity and year.
2. **Reclaims** - table of certificates with reclaim potential, deadline and status (expired, due soon, open), sorted by deadline; card for Reclaims Due Soon.
3. **Data quality** - Open Errors by rule, list of certificates needing review with the finding message.
4. **Filing calendar** - matrix of obligations by entity and state, with owner and days to due; conditional formatting for overdue items.
