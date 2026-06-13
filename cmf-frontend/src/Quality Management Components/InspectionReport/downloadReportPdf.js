import html2canvas from 'html2canvas';
import jsPDF from 'jspdf';

/**
 * Capture the on-screen A4 report sheet and save as a multi-page PDF.
 */
export async function downloadInspectionReportPdf(element, filename = 'Inspection_Report.pdf') {
  if (!element) {
    throw new Error('Report preview is not ready.');
  }

  const prevTransform = element.style.transform;
  const prevTransformOrigin = element.style.transformOrigin;
  const prevBoxShadow = element.style.boxShadow;

  element.style.transform = 'none';
  element.style.transformOrigin = 'top left';
  element.style.boxShadow = 'none';

  try {
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));

    const canvas = await html2canvas(element, {
      scale: 2,
      useCORS: true,
      allowTaint: true,
      logging: false,
      backgroundColor: '#ffffff',
      width: element.scrollWidth,
      height: element.scrollHeight,
      windowWidth: element.scrollWidth,
      windowHeight: element.scrollHeight,
    });

    const imgData = canvas.toDataURL('image/png');
    const pdf = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' });
    const pageWidth = pdf.internal.pageSize.getWidth();
    const pageHeight = pdf.internal.pageSize.getHeight();
    const imgHeight = (canvas.height * pageWidth) / canvas.width;

    let offsetY = 0;
    let page = 0;

    while (offsetY < imgHeight) {
      if (page > 0) pdf.addPage();
      pdf.addImage(imgData, 'PNG', 0, -offsetY, pageWidth, imgHeight);
      offsetY += pageHeight;
      page += 1;
    }

    pdf.save(filename);
  } finally {
    element.style.transform = prevTransform;
    element.style.transformOrigin = prevTransformOrigin;
    element.style.boxShadow = prevBoxShadow;
  }
}
