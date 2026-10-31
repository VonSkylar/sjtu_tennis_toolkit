// Ported from the existing Python browser probes; see tools/sync_probes.py.
globalThis.SJTU_PROBES = (() => {
const geom = {"minVisiblePixels": 4, "paddingX": 20, "paddingTop": 20, "paddingBottom": 80, "cellMinWidth": 25, "cellMaxWidth": 90, "cellMinHeight": 20, "cellMaxHeight": 70, "maxRowDistance": 45, "maxColumnDistance": 60, "cellParentDepth": 5, "cellProbeMaxWidth": 120, "cellProbeMaxHeight": 90, "cellProbeCenterTolerance": 8, "scannerChainDepth": 4, "selectableBlueMinBlue": 185, "selectableBlueMinGreen": 120, "selectableBlueMaxRed": 210, "selectableBlueMinBlueMinusRed": 30, "selectableBlueMinBlueMinusGreen": 8, "selectedGreenMinGreen": 130, "selectedGreenMaxRed": 120, "selectedGreenMaxBlue": 180, "selectedGreenMinGreenMinusRed": 45, "greyMaxChannelDelta": 18, "greyMinRed": 115, "greyMaxRed": 245, "courtCount": 8};

  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return (
      rect.width > geom.minVisiblePixels &&
      rect.height > geom.minVisiblePixels &&
      style.visibility !== 'hidden' &&
      style.display !== 'none'
    );
  };
  const norm = (text) => (text || '').replace(/\s+/g, '').trim();
  const visibleElements = () => Array.from(document.querySelectorAll('body *')).filter(visible);
  const boxIsGridCell = (rect) =>
    rect.width >= geom.cellMinWidth &&
    rect.width <= geom.cellMaxWidth &&
    rect.height >= geom.cellMinHeight &&
    rect.height <= geom.cellMaxHeight;
  const gridBounds = (courtNodes, timeNodes) => ({
    left: Math.min(...courtNodes.map((item) => item.rect.left)) - geom.paddingX,
    right: Math.max(...courtNodes.map((item) => item.rect.right)) + geom.paddingX,
    top: Math.min(...timeNodes.map((item) => item.rect.top)) - geom.paddingTop,
    bottom: Math.max(...timeNodes.map((item) => item.rect.bottom)) + geom.paddingBottom,
  });
  const boxInsideGrid = (rect, bounds) =>
    rect.left >= bounds.left &&
    rect.right <= bounds.right &&
    rect.top >= bounds.top &&
    rect.bottom <= bounds.bottom;
  const rowDistance = (rect, y) => Math.abs(rect.top + rect.height / 2 - y);
  const columnDistance = (rect, x) => Math.abs(rect.left + rect.width / 2 - x);
  const isSelectableBlue = (r, g, b) =>
    b >= geom.selectableBlueMinBlue &&
    g >= geom.selectableBlueMinGreen &&
    r <= geom.selectableBlueMaxRed &&
    b - r >= geom.selectableBlueMinBlueMinusRed &&
    b - g >= geom.selectableBlueMinBlueMinusGreen;
  const isSelectedGreen = (r, g, b) =>
    g >= geom.selectedGreenMinGreen &&
    r <= geom.selectedGreenMaxRed &&
    b <= geom.selectedGreenMaxBlue &&
    g - r >= geom.selectedGreenMinGreenMinusRed;
  const isUnavailableGrey = (r, g, b) =>
    Math.abs(r - g) <= geom.greyMaxChannelDelta &&
    Math.abs(g - b) <= geom.greyMaxChannelDelta &&
    r >= geom.greyMinRed &&
    r <= geom.greyMaxRed;

return {geometry: geom,
cell: ({ targetCourt, targetHour, geom }) => {

              const all = visibleElements();

              const timeNodes = all
                .map((el) => ({ el, text: norm(el.innerText || el.textContent || ''), rect: el.getBoundingClientRect() }))
                .filter((item) => /^\d{2}:00$/.test(item.text))
                .sort((a, b) => a.rect.top - b.rect.top);
              const courtNodes = all
                .map((el) => ({ el, text: norm(el.innerText || el.textContent || ''), rect: el.getBoundingClientRect() }))
                .filter((item) => /^场地\d+$/.test(item.text))
                .sort((a, b) => a.rect.left - b.rect.left);

              const targetTime = timeNodes.find((item) => item.text === targetHour);
              const targetCourtNode = courtNodes.find((item) => item.text === targetCourt);
              if (!targetTime || !targetCourtNode) {
                return { state: 'loading', reason: '目标时间行或场地列还没加载出来' };
              }

              const bounds = gridBounds(courtNodes, timeNodes);
              const targetX = targetCourtNode.rect.left + targetCourtNode.rect.width / 2;
              const targetY = targetTime.rect.top + targetTime.rect.height / 2;

              const rgbValues = (text) => {
                const values = [];
                const pattern = /rgba?\((\d+),\s*(\d+),\s*(\d+)/g;
                let match;
                while ((match = pattern.exec(text.toLowerCase())) !== null) {
                  values.push([Number(match[1]), Number(match[2]), Number(match[3])]);
                }
                return values;
              };

              const hexValues = (text) => {
                const values = [];
                const pattern = /#([0-9a-f]{6})/gi;
                let match;
                while ((match = pattern.exec(text.toLowerCase())) !== null) {
                  const value = match[1];
                  values.push([
                    Number.parseInt(value.slice(0, 2), 16),
                    Number.parseInt(value.slice(2, 4), 16),
                    Number.parseInt(value.slice(4, 6), 16),
                  ]);
                }
                return values;
              };

              const localAncestors = (el, baseRect) => {
                const nodes = [el, ...Array.from(el.querySelectorAll('*'))];
                let current = el.parentElement;
                for (let depth = 0; current && depth < geom.cellParentDepth; depth += 1) {
                  const rect = current.getBoundingClientRect();
                  const centerX = rect.left + rect.width / 2;
                  const centerY = rect.top + rect.height / 2;
                  const baseCenterX = baseRect.left + baseRect.width / 2;
                  const baseCenterY = baseRect.top + baseRect.height / 2;
                  const sameCellArea =
                    rect.width <= geom.cellProbeMaxWidth &&
                    rect.height <= geom.cellProbeMaxHeight &&
                    Math.abs(centerX - baseCenterX) <= geom.cellProbeCenterTolerance &&
                    Math.abs(centerY - baseCenterY) <= geom.cellProbeCenterTolerance;
                  if (!sameCellArea) {
                    break;
                  }
                  nodes.push(current);
                  current = current.parentElement;
                }
                return nodes;
              };

              const classify = (el) => {
                const baseRect = el.getBoundingClientRect();
                const related = localAncestors(el, baseRect);

                const combined = related.map((node) => {
                  const text = norm(node.innerText || node.textContent || '');
                  const title = norm(node.getAttribute('title'));
                  const aria = norm(node.getAttribute('aria-label'));
                  const ariaChecked = norm(node.getAttribute('aria-checked'));
                  const klass = norm(node.className && node.className.toString());
                  const dataState = norm(node.getAttribute('data-state') || node.getAttribute('data-status'));
                  return `${text}|${title}|${aria}|${ariaChecked}|${klass}|${dataState}`;
                }).join('|');

                const colorText = related.map((node) => {
                  const style = window.getComputedStyle(node);
                  return [
                    style.backgroundColor,
                    style.borderColor,
                    style.color,
                    style.fill,
                    style.stroke,
                    style.backgroundImage,
                    node.getAttribute('fill') || '',
                    node.getAttribute('stroke') || '',
                    node.getAttribute('style') || '',
                  ].join(' ');
                }).join(' ');

                const decodedColorText = (() => {
                  try {
                    return decodeURIComponent(colorText);
                  } catch {
                    return colorText;
                  }
                })();
                const colors = [...rgbValues(decodedColorText), ...hexValues(decodedColorText)];
                if (/不可选|已约|已满|禁用|disabled|disable|unavailable|booked|sold|reserved/i.test(combined)) return {state:'unavailable',reason:'格子标记为不可选'};
                const hasGreen = colors.some(([r, g, b]) => isSelectedGreen(r, g, b));
                if (/selected|active|checked|is-checked/i.test(combined) || hasGreen) {
                  return { state: 'selected', reason: '格子已选中' };
                }

                const hasBlue = colors.some(([r, g, b]) => isSelectableBlue(r, g, b));
                if (/available|selectable|free|empty|enabled|optional|appointable/i.test(combined) || hasBlue) {
                  return { state: 'available', reason: '蓝色可选格子' };
                }

                if (/不可选|已约|已满|禁用|disabled|disable|unavailable|booked|sold|reserved/i.test(combined)) {
                  return { state: 'unavailable', reason: '格子标记为不可选' };
                }

                const hasGray = colors.some(([r, g, b]) => isUnavailableGrey(r, g, b));
                if (hasGray) {
                  return { state: 'unavailable', reason: '灰色不可选格子' };
                }

                return { state: 'unknown', reason: '无法识别格子颜色状态' };
              };

              const candidates = all
                .map((el) => ({ el, rect: el.getBoundingClientRect() }))
                .filter((item) => boxInsideGrid(item.rect, bounds) && boxIsGridCell(item.rect))
                .map((item) => ({
                  ...item,
                  centerX: item.rect.left + item.rect.width / 2,
                  centerY: item.rect.top + item.rect.height / 2,
                }))
                .filter((item) =>
                  columnDistance(item.rect, targetX) <= geom.maxColumnDistance &&
                  rowDistance(item.rect, targetY) <= geom.maxRowDistance
                );
              candidates.sort((a, b) => {
                const aDistance = Math.abs(a.centerX - targetX) + Math.abs(a.centerY - targetY);
                const bDistance = Math.abs(b.centerX - targetX) + Math.abs(b.centerY - targetY);
                if (Math.abs(aDistance - bDistance) > 1) {
                  return aDistance - bDistance;
                }
                return (b.rect.width * b.rect.height) - (a.rect.width * a.rect.height);
              });

              const best = candidates[0];
              if (!best) {
                return { state: 'not_found', reason: '没有找到目标格子' };
              }

              const classification = classify(best.el);
              return {
                state: classification.state,
                reason: classification.reason,
                x: best.centerX,
                y: best.centerY,
              };
            }
            ,
scroll: ({ targetHour, geom }) => {

              const timeNode = visibleElements()
                .map((el) => ({ el, text: norm(el.innerText || el.textContent || '') }))
                .find((item) => item.text === targetHour);
              if (!timeNode) {
                return { error: `没有找到 ${targetHour} 时间行，不能滚动到目标位置` };
              }
              timeNode.el.scrollIntoView({ block: 'center', inline: 'nearest' });
              return { ok: true };
            }
            ,
notice: ({ geom }) => {

              const selectors = [
                '.el-message',
                '.ant-message',
                '.van-toast',
                '.toast',
                '[role="alert"]',
                '.message',
                '.notice'
              ];
              const nodes = selectors.flatMap((selector) => Array.from(document.querySelectorAll(selector)));
              const texts = nodes.filter(visible).map((node) => node.innerText || node.textContent || '');
              return texts.join('\n');
            }
            ,
scan: ({ targetHours, geom }) => {

              const all = visibleElements();
              const bodyText = norm(document.body.innerText);

              const timeNodes = all
                .map((el) => ({ el, text: norm(el.innerText), rect: el.getBoundingClientRect() }))
                .filter((item) => /^\d{2}:00$/.test(item.text) && targetHours.includes(item.text))
                .sort((a, b) => a.rect.top - b.rect.top);

              const courtNodes = all
                .map((el) => ({ el, text: norm(el.innerText), rect: el.getBoundingClientRect() }))
                .filter((item) => /^场地\d+$/.test(item.text))
                .sort((a, b) => a.rect.left - b.rect.left);

              if (timeNodes.length === 0 || courtNodes.length === 0) {
                return { error: '没有识别到时间行或场地列。请确认页面停留在网球场预约表格。' };
              }

              const bounds = gridBounds(courtNodes, timeNodes);

              const isAvailable = (el) => {
                const chain = [];
                let current = el;
                for (let depth = 0; current && depth < geom.scannerChainDepth; depth += 1) {
                  chain.push(current);
                  current = current.parentElement;
                }

                const combined = chain.map((node) => {
                  const text = norm(node.innerText);
                  const title = norm(node.getAttribute('title'));
                  const aria = norm(node.getAttribute('aria-label'));
                  const klass = norm(node.className && node.className.toString());
                  const dataState = norm(node.getAttribute('data-state') || node.getAttribute('data-status'));
                  return `${text}|${title}|${aria}|${klass}|${dataState}`;
                }).join('|');

                if (/不可选|已约|已满|禁用|disabled|disable|unavailable|booked|sold|reserved/i.test(combined)) {
                  return false;
                }
                if (/可选|available|selectable|free|empty|enabled|optional|appointable/i.test(combined)) {
                  return true;
                }

                const colorText = chain.map((node) => {
                  const style = window.getComputedStyle(node);
                  return `${style.backgroundColor} ${style.borderColor} ${style.backgroundImage}`;
                }).join(' ').toLowerCase();
                const blueish = /rgb\((\d+),\s*(\d+),\s*(\d+)\)/g;
                let match;
                while ((match = blueish.exec(colorText)) !== null) {
                  const r = Number(match[1]);
                  const g = Number(match[2]);
                  const b = Number(match[3]);
                  if (isSelectableBlue(r, g, b)) {
                    return true;
                  }
                }

                return false;
              };

              const candidates = all
                .map((el) => ({ el, rect: el.getBoundingClientRect() }))
                .filter((item) => boxInsideGrid(item.rect, bounds) && boxIsGridCell(item.rect))
                .filter((item) => isAvailable(item.el));

              const results = [];
              const seen = new Set();

              for (const item of candidates) {
                const centerX = item.rect.left + item.rect.width / 2;
                const centerY = item.rect.top + item.rect.height / 2;
                const hour = timeNodes.reduce((best, node) => {
                  const y = node.rect.top + node.rect.height / 2;
                  const distance = Math.abs(centerY - y);
                  return !best || distance < best.distance ? { node, distance } : best;
                }, null);
                const court = courtNodes.reduce((best, node) => {
                  const x = node.rect.left + node.rect.width / 2;
                  const distance = Math.abs(centerX - x);
                  return !best || distance < best.distance ? { node, distance } : best;
                }, null);

                if (!hour || !court || hour.distance > geom.maxRowDistance || court.distance > geom.maxColumnDistance) {
                  continue;
                }

                const key = `${court.node.text}-${hour.node.text}`;
                if (!seen.has(key)) {
                  seen.add(key);
                  results.push({ court: court.node.text, hour: hour.node.text });
                }
              }

              return {
                slots: results.sort((a, b) => a.hour.localeCompare(b.hour) || a.court.localeCompare(b.court)),
                candidateCount: candidates.length,
              };
            }
            ,
dates: ({ labels, readyCount, geom }) => {

              const bodyText = norm(document.body.innerText);
              const texts = visibleElements()
                .map((el) => norm(el.innerText || el.textContent || ''))
                .filter(Boolean);
              const dateTexts = new Set(
                texts.filter((text) =>
                  /\d{1,2}月\d{1,2}日/.test(text) ||
                  /\d{4}-\d{2}-\d{2}/.test(text)
                )
              );
              return {
                ready: dateTexts.size >= readyCount,
                targetFound: labels.some((label) => bodyText.includes(label)),
                dateCount: dateTexts.size,
              };
            }
            ,
grid: ({ targetHour, geom }) => {

              const all = visibleElements();
              const bodyText = norm(document.body.innerText);

              const loadingSelectors = [
                '.el-loading-mask',
                '.el-loading-spinner',
                '.ant-spin-spinning',
                '.van-loading',
                '.loading',
                '[class*="loading"]',
                '[class*="spin"]'
              ];
              const hasLoading = loadingSelectors.some((selector) =>
                Array.from(document.querySelectorAll(selector)).some(visible)
              ) || /加载中|正在加载/.test(bodyText);
              if (hasLoading) {
                return { ready: false, reason: '页面仍在加载' };
              }

              const timeNodes = all
                .map((el) => ({ text: norm(el.innerText || el.textContent || ''), rect: el.getBoundingClientRect() }))
                .filter((item) => /^\d{2}:00$/.test(item.text));
              const courtNodes = all
                .map((el) => ({ text: norm(el.innerText || el.textContent || ''), rect: el.getBoundingClientRect() }))
                .filter((item) => /^场地\d+$/.test(item.text));

              const targetTime = timeNodes.find((item) => item.text === targetHour);
              if (!targetTime) {
                return { ready: false, reason: `还没看到 ${targetHour} 时间行` };
              }

              const courtSet = new Set(courtNodes.map((item) => item.text));
              for (let court = 1; court <= geom.courtCount; court += 1) {
                if (!courtSet.has(`场地${court}`)) {
                  return { ready: false, reason: `还没看到场地${court}` };
                }
              }

              const bounds = gridBounds(courtNodes, timeNodes);
              const rowCenterY = targetTime.rect.top + targetTime.rect.height / 2;
              const candidates = all
                .map((el) => ({ el, rect: el.getBoundingClientRect() }))
                .filter((item) =>
                  boxInsideGrid(item.rect, bounds) &&
                  boxIsGridCell(item.rect) &&
                  rowDistance(item.rect, rowCenterY) <= geom.maxRowDistance
                );

              return {
                ready: candidates.length >= geom.courtCount,
                reason: candidates.length >= geom.courtCount ? '场地图已加载' : `目标时间行只有 ${candidates.length} 个格子`
              };
            }
            ,
};
})();
