# Power Automate flow: certificate inbox

`flow_definition.json` describes a cloud flow that connects the API to the tools the tax team already uses:

1. **Trigger** - SharePoint *When a file is created in a folder* on the `WHT Certificates/Inbox` folder (PDF files only).
2. **Check_certificate** - HTTP POST of the file (base64) to the `/certificates` endpoint, with retries.
3. **Parse_result** - Parse JSON with the response schema.
4. **Log_in_Excel** - Excel Online (Business) *Add a row into a table* (`CertificateLog`): ID, entity, country, amounts, reclaim potential, status.
5. **Needs_review** - if `error_count > 0`, post a message to the tax team channel in Microsoft Teams.

## Building it in Power Automate

The file follows the workflow definition schema that Power Automate uses inside exported flow packages. The quickest way to get a working flow is to build it in the designer with the same steps and use the file as the reference for expressions:

1. Create an automated cloud flow with the SharePoint trigger above and point it to your site and folder.
2. Add **HTTP** (premium connector; included in the free Power Apps Developer Plan): method `POST`, URI = your API URL, body:
   ```json
   {"file_name": "@{triggerOutputs()?['headers']?['x-ms-file-name']}", "content_base64": "@{base64(triggerBody())}"}
   ```
3. Add **Parse JSON** and paste the schema from `Parse_result` in `flow_definition.json`.
4. Create an Excel workbook with a table named `CertificateLog` and the columns listed in `Log_in_Excel`, then add the Excel step.
5. Add a **Condition** on `error_count` greater than 0 and the Teams *Post message in a chat or channel* step.

The API must be reachable from Power Automate, for example deployed to Azure App Service or exposed for testing through a tunnel.

## Without the premium HTTP connector

Replace step 2 with a custom connector generated from the API's OpenAPI document (`/openapi.json`), or keep the flow to steps 1, 4 and 5 and run `python -m taxdoc run` on a schedule.
