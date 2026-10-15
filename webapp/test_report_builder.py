"""Real editable PPTX -> PDF integration; enabled when an office converter is installed."""
from io import BytesIO
from pathlib import Path
import tempfile
import unittest

import report_builder
from server import Journal


@unittest.skipUnless(report_builder.capabilities()['ready'], 'Install report requirements and LibreOffice or PowerPoint')
class ReportBuilderIntegrationTests(unittest.TestCase):
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
            result=report_builder.build(snapshot,Path(temporary)/'output')
            presentation=Presentation(Path(temporary)/'output/report.pptx')
            pdf=PdfReader(Path(temporary)/'output/report.pdf')
            text='\n'.join(sh.text for slide in presentation.slides for sh in slide.shapes if sh.has_text_frame)
            pdftext='\n'.join(page.extract_text() for page in pdf.pages)
            self.assertEqual(len(presentation.slides),len(pdf.pages))
            self.assertEqual(result['event_count'],7)
            self.assertGreater(result['slide_count'],10)  # long description continues
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
