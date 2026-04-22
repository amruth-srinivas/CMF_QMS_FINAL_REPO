/**
 * Must load before any react-pdf <Document>. Vite bundles the worker from node_modules.
 */
import { pdfjs } from 'react-pdf';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.js?url';

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

export { pdfjs };
