"""Real editable PPTX -> PDF integration; enabled when an office converter is installed."""
from io import BytesIO
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import report_builder
from server import Journal


class PdfExportTests(unittest.TestCase):
    def test_powerpoint_receives_absolute_unicode_paths_and_sta(self):
        with tempfile.TemporaryDirectory() as temporary:
            pptx = Path(temporary) / 'Отчет СМС.pptx'
            pdf = pptx.with_suffix('.pdf')
            pptx.write_bytes(b'presentation')
            def exported(command, **kwargs):
                self.assertIn('-STA', command)
                self.assertEqual(command[-2:], [str(pptx.resolve()), str(pdf.resolve())])
                pdf.write_bytes(b'%PDF-test')
                return subprocess.CompletedProcess(command, 0, b'', b'')
            with patch.object(report_builder.subprocess, 'run', side_effect=exported):
                report_builder.export_pdf(pptx, pdf, ('powerpoint', 'powershell.exe'))
            self.assertTrue(pdf.is_file())

    def test_powerpoint_com_error_is_shown_in_russian_even_with_partial_pdf(self):
        with tempfile.TemporaryDirectory() as temporary:
            pptx = Path(temporary) / 'report.pptx'
            pdf = pptx.with_suffix('.pdf')
            pdf.write_bytes(b'%PDF-incomplete')
            diagnostic = {'stage': 'save', 'hresult': '0x80004005', 'message': 'Не удалось сохранить файл'}
            output = ('SMS_POWERPOINT_ERROR=' + json.dumps(diagnostic, ensure_ascii=False)).encode('utf-8')
            result = subprocess.CompletedProcess([], 1, output, b'')
            with patch.object(report_builder.subprocess, 'run', return_value=result):
                with self.assertRaises(report_builder.BuildError) as raised:
                    report_builder.export_pdf(pptx, pdf, ('powerpoint', 'powershell.exe'))
            for text in ['PowerPoint', 'сохранение PDF', '0x80004005', diagnostic['message'], 'Предыдущие файлы сохранены']:
                self.assertIn(text, str(raised.exception))

    def test_success_exit_without_pdf_is_rejected_and_powershell_stderr_is_visible(self):
        with tempfile.TemporaryDirectory() as temporary:
            pptx = Path(temporary) / 'report.pptx'
            result = subprocess.CompletedProcess([], 0, b'', b'Script execution failed')
            with patch.object(report_builder.subprocess, 'run', return_value=result):
                with self.assertRaisesRegex(report_builder.BuildError, 'Script execution failed'):
                    report_builder.export_pdf(pptx, pptx.with_suffix('.pdf'), ('powerpoint', 'powershell.exe'))

    def test_powerpoint_timeout_mentions_blocking_dialogs(self):
        with tempfile.TemporaryDirectory() as temporary:
            pptx = Path(temporary) / 'report.pptx'
            with patch.object(report_builder.subprocess, 'run', side_effect=subprocess.TimeoutExpired('powershell', 180)):
                with self.assertRaisesRegex(report_builder.BuildError, 'активации.*Предыдущие файлы сохранены'):
                    report_builder.export_pdf(pptx, pptx.with_suffix('.pdf'), ('powerpoint', 'powershell.exe'))


@unittest.skipUnless(report_builder.capabilities()['ready'], 'Install report requirements and LibreOffice or PowerPoint')
class ReportBuilderIntegrationTests(unittest.TestCase):
    def test_new_q4_report_changes_period_plan_and_does_not_reuse_q3_photos(self):
        import hashlib
        import zipfile
        from PIL import Image
        from pptx import Presentation
        from pypdf import PdfReader
        with tempfile.TemporaryDirectory() as temporary:
            journal=Journal(Path(temporary)/'data')
            new=journal.save(None,{'name':'Командная встреча октября','date':'2026-10-18','quarter':'2026-Q4',
                                  'description':'Совместное обсуждение проектов и обмен опытом.','organizer':'Совет молодых специалистов'})
            image=BytesIO()
            Image.new('RGB',(120,80),'#1279a2').save(image,'PNG')
            journal.upload(new['id'],image.getvalue(),'q4-group.png')
            excluded=journal.save(None,{'name':'Исключенная встреча','quarter':'2026-Q4','include':False})
            archived=journal.save(None,{'name':'Архивная встреча','quarter':'2026-Q4'})
            journal.archive(archived['id'],True)
            snapshot=journal.report_snapshot('2026-Q4')
            result=report_builder.build(snapshot,Path(temporary)/'output')
            presentation=Presentation(Path(temporary)/'output/report.pptx')
            pdf=PdfReader(Path(temporary)/'output/report.pdf')
            self.assertIn('IV квартал 2026',presentation.core_properties.title)
            text=' '.join(' '.join(page.extract_text().split()) for page in pdf.pages)
            self.assertEqual((result['event_count'],result['slide_count'],len(pdf.pages)),(1,4,4))
            self.assertIn('IV КВАРТАЛ 2026 ГОДА',text)
            self.assertIn('В IV КВАРТАЛЕ 2026 ГОДА',text)
            self.assertIn('НА I КВАРТАЛ 2027 ГОДА',text)
            self.assertIn('Командная встреча октября',text)
            for prior in ['III КВАРТАЛ','Ночная Тула','Гонка героев','Исключенная встреча','Архивная встреча','Первый год в ЦКБА']:
                self.assertNotIn(prior,text)
            template=Presentation(snapshot['template'])
            oldphotos={hashlib.sha256(shape.image.blob).digest() for slide in list(template.slides)[:2] for shape in list(slide.shapes)[:3] if shape.shape_type==13}
            newphotos={hashlib.sha256(shape.image.blob).digest() for slide in presentation.slides for shape in slide.shapes if shape.shape_type==13}
            self.assertFalse(oldphotos & newphotos)
            with zipfile.ZipFile(Path(temporary)/'output/report.pptx') as archive:
                embedded={hashlib.sha256(archive.read(name)).digest() for name in archive.namelist() if name.startswith('ppt/media/')}
            self.assertFalse(oldphotos & embedded)
            self.assertTrue(any(shape.shape_type==13 and 'q4-group.png' in shape.name for shape in presentation.slides[1].shapes))

    def test_changed_fields_membership_photos_and_long_text_reach_both_formats(self):
        from PIL import Image
        from pptx import Presentation
        from pypdf import PdfReader
        with tempfile.TemporaryDirectory() as temporary:
            journal=Journal(Path(temporary)/'data')
            event=journal.event('dragon_boat_cup')
            description='Новая редакция: контрольные пункты и командные задания. ' * 36
            journal.save(event['id'],{'revision':event['revision'],'name':'Обновленный кубок дракона',
                                     'description':description,'organizer':'Совет ЦКБА',
                                     'total_attendance':21,'sms_attendance':18})
            journal.archive('hero_race',True)
            event=journal.event('orienteering_2026_08_30')
            journal.save(event['id'],{'revision':event['revision'],'date':'2026-10-15','quarter':'2026-Q4'})
            new=journal.save(None,{'name':'Новая встреча молодежи','quarter':'2026-Q3',
                                  'description':'Итоговое обсуждение.','sms_attendance':None})
            stream=BytesIO()
            Image.new('RGB',(120,80),'#1279a2').save(stream,'PNG')
            uploaded=journal.upload(new['id'],stream.getvalue(),'new-group.png')
            snapshot=journal.report_snapshot('2026-Q3')
            for card in snapshot['events']:
                cached=card.setdefault('source',{}).setdefault('report_content',{})
                cached['sms_attendance_display']=f"{card.get('sms_attendance')} человек (расчетно: старое пояснение)"
                cached['team_attendance_display']=f"{card.get('total_attendance')} человек (по фото команды)"
            result=report_builder.build(snapshot,Path(temporary)/'output')
            presentation=Presentation(Path(temporary)/'output/report.pptx')
            pdf=PdfReader(Path(temporary)/'output/report.pdf')
            text='\n'.join(sh.text for slide in presentation.slides for sh in slide.shapes if sh.has_text_frame)
            pdftext='\n'.join(page.extract_text() for page in pdf.pages)
            self.assertEqual(len(presentation.slides),len(pdf.pages))
            self.assertEqual(result['event_count'],7)
            self.assertGreater(result['slide_count'],10)  # long description continues
            # Even existing cached report_content can contain old count qualifiers.
            # Check the actual rendered fields on every event and continuation slide.
            for slide in presentation.slides:
                shapes=list(slide.shapes)
                for index,shape in enumerate(shapes[:-1]):
                    if shape.has_text_frame and shape.text in ['Количество участников из СМС:','Общее количество участников команды:']:
                        self.assertRegex(shapes[index+1].text,r'^(?:\d+|—) человек(?:а)?$')
            for value in ['Обновленный кубок дракона','Совет ЦКБА','Новая встреча молодежи','18 человек']:
                self.assertIn(value,text)
                self.assertIn(value,pdftext)
            self.assertNotIn('Гонка героев',text)
            self.assertNotIn('Соревнования по спортивному ориентированию',text)
            self.assertEqual(text.count('Новая редакция:'),36)
            first=result['event_slides'][new['id']]-1
            photos=[shape for shape in presentation.slides[first].shapes if shape.shape_type==13 and shape.top==2286000]
            self.assertEqual(len(photos),1)
            self.assertIn('new-group.png',photos[0].name)
            self.assertEqual(Path(journal.report_snapshot('2026-Q3')['files'][uploaded['photos'][0]['id']]['path']).read_bytes(),stream.getvalue())


if __name__=='__main__':
    unittest.main()
