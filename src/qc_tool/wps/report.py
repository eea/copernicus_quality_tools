import json
from contextlib import ExitStack
from datetime import datetime
from os.path import normpath
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import Frame, Image, PageTemplate, Paragraph, BaseDocTemplate,Table, TableStyle


def overall_status(job_result):
    step_statuses = [step_result["status"] for step_result in job_result["steps"]]
    if all(step_status == "ok" for step_status in step_statuses):
        return "Checks Passed"
    elif any(step_status in ["failed", "aborted"] for step_status in step_statuses):
        return "Checks Failed"
    else:
        return "Partial (some checks skipped)"

def generate_pdf_report(job_report_filepath, job_result):
    # set report page size to A4
    doc = BaseDocTemplate(str(job_report_filepath), pagesize=A4)

    # Set custom styles
    styles = getSampleStyleSheet()
    style_body = styles["BodyText"]
    style_normal = styles["Normal"]
    style_check_default = ParagraphStyle("status_other", parent=style_normal)
    style_check_ok = ParagraphStyle("status_ok", parent=style_normal, textColor=colors.green)
    style_check_failed = ParagraphStyle("status_failed", parent=style_normal, textColor=colors.red)
    style_check_partial = ParagraphStyle("status_partial", parent=style_normal, textColor=colors.orange)

    # Create page footer.
    def footer(canvas, doc):
        canvas.saveState()
        styles = getSampleStyleSheet()
        style_normal = styles["Normal"]
        p = Paragraph("QC Tool Check Report - {:s}  ".format(job_result["filename"]), style_normal)
        w, h = p.wrap(doc.width, doc.bottomMargin)
        p.drawOn(canvas, doc.leftMargin, h)
        canvas.restoreState()

    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="frame_normal")
    template = PageTemplate(id="report_page_template", frames=frame, onPage=footer)
    doc.addPageTemplates([template])

    # Setup main document object.
    text = []

    # Add logo images. The three logos are placed inside an invisible table.
    report_logo_dirpath = Path(normpath(str(Path(__file__).joinpath("../report_images"))))
    with open(str(report_logo_dirpath.joinpath("copernicus_logo_resized.png")), "rb") as copernicus_f, \
        open(str(report_logo_dirpath.joinpath("eea_full_logo_resized.png")), "rb") as eea_f, \
        open(str(report_logo_dirpath.joinpath("land_monitoring_logo_resized.png")), "rb") as land_f:

        copernicus_image = Image(copernicus_f, width=123, height=53)
        eea_image = Image(eea_f, width=178, height=38)
        land_image = Image(land_f, width=124, height=57)
        image_data = [[copernicus_image, land_image, eea_image]]
        image_table=Table(image_data, hAlign="CENTER", colWidths=[130, 150, 200], rowHeights=60)
        image_table_style = TableStyle([("VALIGN", (0, 0), (-1,-1), "CENTER")])
        image_table.setStyle(image_table_style)
        text.append(image_table)
        text.append(Paragraph("", style_normal))

        # Add main heading
        text.append(Paragraph("QC tool check report", styles["Heading1"]))

        # Add summary table
        text.append(Paragraph("", styles["Heading1"]))
        text.append(Paragraph("Report summary", styles["Heading2"]))
        status_file = ["File name", job_result["filename"]]
        status_product = ["Product", job_result["product_ident"]]
        display_date = datetime.strptime(job_result["job_finish_date"], "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d %H:%M:%S")
        status_date = ["Checked on", display_date]
        status_result = overall_status(job_result)
        if status_result == "Checks Passed":
            status_result_style = style_check_ok
        elif status_result == "Checks Failed":
            status_result_style = style_check_failed
        else:
            status_result_style = style_check_partial

        status_result = ["Overall result", Paragraph(status_result, status_result_style)]
        summary_data = [status_file, status_product, status_date, status_result]
        summary_table = Table(summary_data, hAlign="LEFT", colWidths=[90, None])
        summary_style = TableStyle([("INNERGRID", (0, 0), (-1, -1), 0.25, colors.black),
                                    ("BOX", (0, 0), (-1, -1), 0.25, colors.black),
                                    ("VALIGN", (0, 0), (-1,-1), "TOP")])
        summary_table.setStyle(summary_style)
        text.append(summary_table)

        # Detail table title
        text.append(Paragraph("", style_normal))
        text.append(Paragraph("", style_normal))
        text.append(Paragraph("Report details", styles["Heading2"]))

        # Detail table header row
        check_table_header = [Paragraph("<b>CHECK</b>", style_normal),
                              Paragraph("<b>DESCRIPTION</b>", style_normal),
                              Paragraph("<b>STATUS</b>", style_normal),
                              Paragraph("<b>MESSAGES</b>", style_normal)]
        check_data = [check_table_header]

        # Detail table data. Text colour is displayed based on check status.
        for step_result in job_result["steps"]:
            step_status = step_result["status"]
            if step_status is None:
                step_status = "skipped"
            if step_status == "ok":
                display_ident = Paragraph(step_result["check_ident"], style_check_default)
                display_description = Paragraph(step_result["description"], style_check_default)
                display_status = Paragraph("<b>" + step_status + "</b>", style_check_ok)
            elif step_status in ["aborted", "failed", "error"]:
                display_ident = Paragraph(step_result["check_ident"], style_check_failed)
                display_status = Paragraph(step_status, style_check_failed)
                display_description = Paragraph(step_result["description"], style_check_failed)
            else:
                display_ident = Paragraph(step_result["check_ident"], style_check_default)
                display_status = Paragraph(step_status, style_check_default)
                display_description = Paragraph(step_result["description"], style_check_default)

            messages = step_result.get("messages", [])
            if messages is None:
                messages = []
            display_messages = []
            for message in messages:
                display_messages.append(Paragraph(message, style_body))

            check_info = [display_ident,
                          display_description,
                          display_status,
                          display_messages
                          ]
            check_data.append(check_info)

        detail_table=Table(check_data, hAlign="LEFT", colWidths=[90, None, 60, None])
        detail_table_style = TableStyle([("INNERGRID", (0, 0), (-1, -1), 0.25, colors.black),
                                         ("BOX", (0, 0), (-1, -1), 0.25, colors.black),
                                         ("VALIGN", (0, 0), (-1,-1), "TOP")])
        detail_table.setStyle(detail_table_style)
        text.append(detail_table)

        text.append(Paragraph("", style_normal))
        text.append(Paragraph("", style_normal))
        text.append(Paragraph("", style_normal))

        doc.build(text)
