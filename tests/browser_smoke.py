"""真實 Edge DOM／截圖驗證；僅驗證環境需已有 Playwright，應用程式不依賴它。"""
import json
from pathlib import Path
import tempfile

from playwright.sync_api import sync_playwright

from reader.archive import ROOT
from tests.fixtures import FIXTURES, generate
from tests.test_launch import launch, await_ready, stop


def main():
    generate()
    records = []
    with tempfile.TemporaryDirectory() as temporary:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(Path(temporary)/'edge-profile'), channel='msedge', headless=True,
                viewport={'width':1400,'height':900}, locale='zh-TW', accept_downloads=False)
            try:
                for fixture in sorted(FIXTURES.glob('*.chm')):
                    ready=Path(temporary)/'ready.json'
                    ready.unlink(missing_ok=True)
                    process=launch(fixture,ready)
                    info=None
                    page=None
                    try:
                        info=await_ready(process,ready)
                        page=context.new_page()
                        errors=[]
                        page.on('pageerror',lambda error:errors.append(str(error)))
                        page.goto(info['url'])
                        page.wait_for_load_state('networkidle')
                        page.locator('#toc button').nth(1).wait_for()
                        assert page.locator('#toc button').count()==2
                        assert '測試目錄' in page.locator('#toc').inner_text()
                        page.locator('#toc button').nth(1).click()
                        frame=page.frame_locator('#page')
                        frame.locator('#hit').wait_for()
                        expected='電腦' if 'Big5' in fixture.name else '电脑'
                        assert expected in frame.locator('body').inner_text()
                        assert frame.locator('img').evaluate('(img)=>img.complete && img.naturalWidth===80')
                        color=frame.locator('body').evaluate('(body)=>getComputedStyle(body).color')
                        assert color=='rgb(31, 61, 46)',color
                        frame.get_by_text('返回首頁',exact=True).click()
                        frame.locator('#back').wait_for()
                        frame.get_by_text('開啟中文頁面',exact=True).click()
                        frame.locator('#hit').wait_for()
                        page.locator('#query').fill('電腦')
                        page.locator('#search button').click()
                        page.locator('#matches button').wait_for()
                        assert expected in page.locator('#matches').inner_text()
                        page.locator('#matches button').first.click()
                        frame.locator('mark[data-chm-hit]').first.wait_for()
                        assert frame.locator('mark[data-chm-hit]').count()==4
                        assert '3 處' in page.locator('#status').inner_text()
                        # 長頁面尾端的跨節點命中，必須真的捲動。
                        page.locator('#query').fill('跨標籤：電腦')
                        page.locator('#search button').click()
                        page.locator('#matches button').wait_for()
                        page.locator('#matches button').first.click()
                        frame.locator('mark[data-chm-hit]').first.wait_for()
                        page.wait_for_function("document.querySelector('#page').contentWindow.scrollY>400")
                        assert frame.locator('mark[data-chm-hit]').count()==2
                        assert '1 處' in page.locator('#status').inner_text()
                        if 'GB18030' in fixture.name:
                            assert '𠀀' in frame.locator('#hit').inner_text()
                        # 手動編碼及還原均透過 UI 重新解碼、重建目錄。
                        codec='cp950' if 'Big5' in fixture.name else ('utf-8' if 'UTF-8' in fixture.name else 'gb18030')
                        page.locator('#encoding').select_option(codec)
                        page.wait_for_function('document.querySelector("#encoding").value==='+json.dumps(codec))
                        frame.locator('#back').wait_for()
                        page.locator('#encoding').select_option('auto')
                        frame.locator('#back').wait_for()
                        page.locator('#query').fill('電腦')
                        page.locator('#search button').click()
                        page.locator('#matches button').wait_for()
                        page.locator('#matches button').first.click()
                        frame.locator('mark[data-chm-hit]').first.wait_for()
                        screenshot='browser-'+fixture.stem+'.png'
                        assert not errors,errors
                        records.append({'fixture':fixture.name,'browser':'Microsoft Edge / headless',
                                        'toc':page.locator('#toc').inner_text(),
                                        'search':page.locator('#matches').inner_text(),
                                        'css_color':color,'image_width':80,'cross_node_marks':2,
                                        'scrolled':True,'encoding_switch':'PASS','errors':errors,
                                        'screenshot':screenshot,'result':'PASS'})
                        print('PASS',fixture.name,'目錄／圖片／CSS／站內連結／繁簡搜尋／跨節點標示與捲動／手動編碼',flush=True)
                    finally:
                        if page:
                            page.close()
                        output=stop(process,info)
                        assert process.returncode==0,output.decode('utf-8',errors='replace')
            finally:
                context.close()


if __name__=='__main__':
    main()
