from artifact_tool import Workbook,SpreadsheetFile
from pathlib import Path
p=Path(__file__).parent/'static'/'excel_import_template.xlsx'
wb=Workbook.create();ws=wb.worksheets.add('Зээл импорт')
headers=['kind','name','registration','phone','contract','amount','rate','penalty_rate','months','start_date','method']
ws.get_range('A1:K1').values=[headers]
ws.get_range('A2:K3').values=[['Байгууллага','Жишээ ХХК','9999999','99000000','DEMO-001',100000000,24,4.8,12,'2026-01-15','annuity'],['Иргэн','Жишээ иргэн','АА00000000','88000000','DEMO-002',10000000,18,3.6,6,'2026-02-01','equal']]
ws.get_range('A1:K1').format.fill='#16355B';ws.get_range('A1:K1').format.font.color='#FFFFFF';ws.get_range('A1:K1').format.font.bold=True
ws.get_range('A:K').format.column_width=16
ws.get_range('B:B').format.column_width=24
ws.get_range('F:F').format.column_width=22
ws.freeze_panes.freeze_rows(1)
info=wb.worksheets.add('Заавар');info.get_range('A1:B8').values=[['Багана','Тайлбар'],['kind','Иргэн / Байгууллага'],['rate','Жилийн хүү, жишээ 24 = 24%'],['penalty_rate','Нэмэгдүүлсэн ЖИЛИЙН хүү, 4.8 = 4.8%'],['start_date','YYYY-MM-DD формат'],['method','annuity / equal / bullet'],['amount','MNT'],['Анхаар','Демо өгөгдлүүдийг өөрчилж импортлоорой']];info.get_range('A:B').format.column_width=30
SpreadsheetFile.export_xlsx(wb).save(str(p));print(p,p.stat().st_size)
