# Money Graph Frontend

React + TypeScript + Vite interface for exploring a financial network.

## Run locally

```bash
npm install
npm run dev
```

Open the local URL printed by Vite. Use `npm run build` to create a production build.

## Included views

- **Overview** — workspace introduction and analysis summary.
- **Network** — Cytoscape graph view for directed transfers, GID search, role and cluster filters, and entity details.
- **Priority** — searchable, sortable risk table with CSV export.
- **Clusters** — three connected communities linked to the network view.
- **Investigation** — case list linked to relevant entities.

No entity, transfer, risk, cluster, or case records are bundled with the interface. Until verified analysis results are supplied, each page displays an unavailable-data state rather than invented values.

`src/data.ts` contains the frontend presentation types and an empty snapshot. The mapping from the project's three Parquet files to these views must follow the actual processing pipeline and its agreed output schema.
