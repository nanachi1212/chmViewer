"""真實 Edge DOM／截圖驗證；僅驗證環境需已有 Playwright，應用程式不依賴它。"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from reader.archive import ROOT
from tests.fixtures import FIXTURES, generate
from tests.test_launch import launch, await_ready, stop


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path, help='改用已打包的 Windows 執行檔')
    parser.add_argument('--htw', type=Path, help='加測 HTW2.12.3 大型 CHM')
    args = parser.parse_args()
    generate()
    records = []
    with tempfile.TemporaryDirectory() as temporary:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(Path(temporary)/'edge-profile'), channel='msedge', headless=True,
                viewport={'width':1400,'height':900}, locale='zh-TW', accept_downloads=False)
            try:
                fixtures = sorted(FIXTURES.glob('*.chm'))
                if args.htw:
                    fixtures.append(args.htw)
                for number,fixture in enumerate(fixtures):
                    ready=Path(temporary)/'ready.json'
                    ready.unlink(missing_ok=True)
                    started = time.perf_counter()
                    with patch.dict(os.environ, LOCALAPPDATA=str(Path(temporary) / 'reader-settings')):
                        if args.exe:
                            process = subprocess.Popen([args.exe.resolve(), fixture, '--no-browser', '--ready-file', ready],
                                                       cwd=temporary, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                        else:
                            process=launch(fixture,ready)
                    info=None
                    page=None
                    try:
                        info=await_ready(process,ready)
                        page=context.new_page()
                        errors=[]
                        page.on('pageerror',lambda error:errors.append(str(error)))
                        page.goto(info['url'])
                        if fixture == args.htw:
                            frame = page.frame_locator('#page')
                            frame.locator('#winchm_template_content').get_by_text('零：简介', exact=True).first.wait_for()
                            assert '欢迎来到主神空间' in frame.locator('body').inner_text()
                            open_time = time.perf_counter() - started
                            title = frame.locator('#winchm_template_content strong').first
                            size = lambda node: node.evaluate('n=>parseFloat(getComputedStyle(n).fontSize)')
                            assert page.locator('#fontFamily').input_value() == 'PMingLiU'
                            assert 'PMingLiU' in title.evaluate('n=>getComputedStyle(n).fontFamily')
                            assert page.locator('#lineHeight').input_value() == '180'
                            ratio = title.evaluate("""n=>{
                                const style = getComputedStyle(n);
                                return parseFloat(style.lineHeight)/parseFloat(style.fontSize);
                            }""")
                            assert abs(ratio - 1.8) < 0.01
                            assert page.locator('#fontSize').input_value() == '150'
                            large_size = size(title)
                            page.locator('#fontSize').select_option('100')
                            assert abs(large_size - size(title) * 1.5) < 0.02
                            assert page.locator('#toc .toc-page').count() == 4713
                            assert page.locator('#toc .toc-row:visible').count() == 6
                            rules = page.get_by_role('button', name='基础规则', exact=True)
                            rules.click()
                            intro = page.get_by_role('button', name='前言', exact=True)
                            intro.click()
                            home = page.get_by_role('button', name='零：简介', exact=True)
                            home.wait_for()
                            rules.click()
                            assert not home.is_visible()
                            rules.click()
                            home.wait_for()
                            search_started = time.perf_counter()
                            page.locator('#query').fill('強化')
                            page.locator('#search button').click()
                            page.get_by_role('heading', name='搜尋結果（4132 頁）').wait_for()
                            search_time = time.perf_counter() - search_started
                            assert page.locator('#matches button').count() == 100
                            page.locator('#more').click()
                            assert page.locator('#matches button').count() == 200
                            page.locator('#matches button').nth(100).click()
                            frame.locator('mark[data-chm-hit]').first.wait_for()
                            assert '强化' in ''.join(frame.locator('mark[data-chm-hit]').all_text_contents())
                            result_url = frame.locator('body').evaluate('node=>node.ownerDocument.URL')
                            page.get_by_role('button', name='返回完整目錄').click()
                            home.wait_for()
                            assert page.locator('#toc .toc-page').count() == 4713
                            assert not page.locator('#results').is_visible()
                            assert frame.locator('body').evaluate('node=>node.ownerDocument.URL') == result_url
                            assert frame.locator('mark[data-chm-hit]').count() == 0
                            assert page.locator('#query').input_value() == ''
                            home.click()
                            frame.locator('#winchm_template_content').get_by_text('零：简介', exact=True).wait_for()
                            page.locator('#query').fill('無此字串123987xyz')
                            page.locator('#search button').click()
                            page.get_by_role('heading',name='搜尋結果（0 頁）').wait_for()
                            page.locator('#query').fill('')
                            home.wait_for()
                            assert not errors, errors
                            print(f'PASS HTW2.12.3：4,713 頁，開啟至首頁 {open_time:.2f}s，'
                                  f'繁體搜尋「強化」至顯示 4,132 頁結果 {search_time:.2f}s，'
                                  '展開、收合、完整目錄返回、保留閱讀頁與無結果返回均通過。', flush=True)
                            continue
                        page.wait_for_load_state('networkidle')
                        page.locator('#toc .toc-toggle').click()
                        page.locator('#toc .toc-page').nth(1).wait_for()
                        assert page.locator('#toc .toc-page').count()==2
                        assert '測試目錄' in page.locator('#toc').inner_text()
                        page.locator('#toc .toc-page').nth(1).click()
                        frame=page.frame_locator('#page')
                        frame.locator('#hit').wait_for()
                        expected='電腦' if 'Big5' in fixture.name else '电脑'
                        assert expected in frame.locator('body').inner_text()
                        assert frame.locator('img').evaluate('(img)=>img.complete && img.naturalWidth===80')
                        color=frame.locator('body').evaluate('(body)=>getComputedStyle(body).color')
                        assert color=='rgb(31, 61, 46)',color
                        font = page.get_by_label('內文字級')
                        family = page.get_by_label('內文字體')
                        spacing = page.get_by_label('文字間距')
                        line_height = page.get_by_label('行距', exact=True)
                        assert font.input_value() == ('100' if number==0 else '150')
                        assert family.input_value() == ('original' if number==0 else 'PMingLiU')
                        assert line_height.input_value() == ('0' if number==0 else '180')
                        font.select_option('100')
                        family.select_option('original')
                        spacing.select_option('0')
                        line_height.select_option('0')
                        hit = frame.locator('#hit')
                        hit.evaluate("""node=>{
                            node.style.setProperty('font-size','18px','important');
                            node.style.setProperty('font-family','serif','important');
                            node.style.lineHeight='24px';
                            node.querySelector('b').style.fontSize='1.5em';
                        }""")
                        original_style = hit.get_attribute('style')
                        image_width = frame.locator('img').bounding_box()['width']
                        for percent in (200,75,125,100):
                            font.select_option(str(percent))
                            sizes = hit.evaluate("""n=>[getComputedStyle(n).fontSize,getComputedStyle(n).lineHeight,
                                getComputedStyle(n.querySelector('b')).fontSize].map(v=>parseFloat(v))""")
                            assert sizes == [n*percent/100 for n in (18,24,27)], (percent,sizes)
                            assert frame.locator('img').bounding_box()['width'] == image_width
                        assert hit.get_attribute('style') == original_style
                        probe = frame.locator('#line-height-probe')
                        hit.evaluate("""node=>{
                            const sample = node.ownerDocument.createElement('div');
                            sample.id = 'line-height-probe';
                            sample.setAttribute('style', 'font: 20px/22px serif !important');
                            sample.innerHTML = '<span>第一行</span><br><span>第二行</span>';
                            node.after(sample);
                        }""")
                        line_distance = """node=>node.lastElementChild.getBoundingClientRect().top
                            - node.firstElementChild.getBoundingClientRect().top"""
                        assert probe.evaluate(line_distance) == 22
                        line_height.select_option('180')
                        assert probe.evaluate(line_distance) == 36
                        family.select_option('DFKai-SB')
                        assert 'DFKai-SB' in hit.evaluate('n=>getComputedStyle(n).fontFamily')
                        spacing.select_option('10')
                        font.select_option('150')
                        assert hit.evaluate("""n=>[getComputedStyle(n).fontFamily.includes('DFKai-SB'),
                            getComputedStyle(n).fontSize, getComputedStyle(n).letterSpacing,
                            parseFloat(getComputedStyle(n).lineHeight)]""") == [True, '27px', '3px', 48.6]
                        line_height.select_option('0')
                        assert hit.evaluate('n=>getComputedStyle(n).lineHeight') == '36px'
                        font.select_option('100')
                        family.select_option('original')
                        spacing.select_option('0')
                        assert hit.get_attribute('style') == original_style
                        assert probe.evaluate(line_distance) == 22
                        assert hit.evaluate('n=>getComputedStyle(n).fontFamily') == 'serif'
                        family.select_option('PMingLiU')
                        font.select_option('150')
                        line_height.select_option('180')
                        frame.get_by_text('返回首頁',exact=True).click()
                        frame.locator('#back').wait_for()
                        frame.get_by_text('開啟中文頁面',exact=True).click()
                        frame.locator('#hit').wait_for()
                        assert frame.locator('#hit').evaluate('n=>getComputedStyle(n).fontSize') == '30px'
                        assert frame.locator('#hit').evaluate('n=>getComputedStyle(n).lineHeight') == '54px'
                        assert 'PMingLiU' in frame.locator('#hit').evaluate('n=>getComputedStyle(n).fontFamily')
                        page.locator('#query').fill('電腦')
                        page.locator('#search button').click()
                        page.locator('#matches button').wait_for()
                        assert expected in page.locator('#matches').inner_text()
                        page.locator('#matches button').first.click()
                        frame.locator('mark[data-chm-hit]').first.wait_for()
                        assert frame.locator('mark[data-chm-hit]').count()==4
                        assert frame.locator('mark[data-chm-hit]').last.evaluate('n=>getComputedStyle(n).fontSize') == '30px'
                        assert 'PMingLiU' in frame.locator('mark[data-chm-hit]').first.evaluate('n=>getComputedStyle(n).fontFamily')
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
