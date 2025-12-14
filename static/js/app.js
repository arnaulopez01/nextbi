// static/js/app.js

// Variables de Estado
let currentFileSummary = null;
let currentFilePath = null;
let currentDashId = null; 
let activeFilters = {};   
let mapInstances = {}; 
let pieColorMap = {};

document.addEventListener('DOMContentLoaded', () => {
    if(document.getElementById("historyList")) {
        loadHistory();
    }
});

// --- GESTIÓN DE SESIÓN ---
async function logout() {
    await fetch("/api/logout", { method: "POST" });
    window.location.href = "/";
}

// --- SUBIDA ---
const fileInput = document.getElementById("fileInput");
if(fileInput) {
    fileInput.addEventListener("change", async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const label = document.getElementById("fileName");
        label.textContent = "Subiendo...";
        const formData = new FormData();
        formData.append("file", file);
        try {
            const res = await fetch("/upload_and_analyze", { method: "POST", body: formData });
            const data = await res.json();
            if (data.error) throw new Error(data.error);
            
            currentFileSummary = data.summary;
            currentFilePath = data.file_path;
            if(data.original_name) fileInput.dataset.originalName = data.original_name;

            label.textContent = "✅ " + file.name;
            label.classList.add("text-green-600");
            document.getElementById("promptContainer").classList.remove("opacity-50", "pointer-events-none");
        } catch (err) { alert(err.message); }
    });
}

// --- GENERACIÓN ---
async function generate() {
    const instruction = document.getElementById("prompt").value;
    const originalName = document.getElementById("fileInput").dataset.originalName;

    document.getElementById("inputSection").classList.add("hidden");
    document.getElementById("loader").classList.remove("hidden");
    document.getElementById("loader").classList.add("flex");

    try {
        const res = await fetch("/generate_dashboard", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                file_path: currentFilePath,
                summary: currentFileSummary,
                instruction: instruction,
                original_name: originalName
            })
        });
        const config = await res.json();
        if (config.error) throw new Error(config.error);

        await loadHistory();
        const firstItem = document.querySelector("#historyList > div > div");
        if(firstItem) firstItem.click(); 

    } catch (e) {
        alert("Error: " + e.message);
        document.getElementById("inputSection").classList.remove("hidden");
        document.getElementById("loader").classList.add("hidden");
    }
}

// --- HISTORIAL ---
async function loadHistory() {
    const list = document.getElementById("historyList");
    if (!list) return;
    try {
        const res = await fetch("/api/dashboards");
        const items = await res.json();
        list.innerHTML = "";
        if (items.length === 0) {
            list.innerHTML = '<p class="text-xs text-slate-500 text-center mt-4">Sin historial</p>';
            return;
        }
        items.forEach(item => {
            const div = document.createElement("div");
            div.className = "group flex items-center justify-between p-3 mb-1 rounded-xl cursor-pointer hover:bg-slate-50 transition border border-transparent hover:border-slate-200";
            div.innerHTML = `
                <div class="flex-grow min-w-0 pr-2" onclick="loadDashboard('${item.id}')">
                    <div class="font-medium text-slate-600 group-hover:text-indigo-600 truncate text-sm transition">${item.title}</div>
                    <div class="text-[10px] text-slate-400">${new Date(item.created_at).toLocaleDateString()}</div>
                </div>
                <button onclick="deleteDashboard('${item.id}', event)" class="opacity-0 group-hover:opacity-100 p-1.5 text-slate-400 hover:text-red-500 hover:bg-slate-100 rounded-lg transition-all" title="Borrar">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                </button>
            `;
            list.appendChild(div);
        });
    } catch(e) { console.error(e); }
}

async function deleteDashboard(id, event) {
    event.stopPropagation();
    if (!confirm("¿Eliminar?")) return;
    await fetch(`/api/dashboards/${id}`, { method: "DELETE" });
    loadHistory();
    if(currentDashId === id) resetView();
}

async function loadDashboard(id) {
    currentDashId = id;
    activeFilters = {}; 
    mapInstances = {}; 
    pieColorMap = {};
    
    const inputSec = document.getElementById("inputSection");
    if(inputSec) inputSec.classList.add("hidden");

    document.getElementById("dashboardGrid").innerHTML = "";
    
    const loader = document.getElementById("loader");
    if(loader) {
        loader.classList.remove("hidden");
        loader.classList.add("flex");
    }

    try {
        const res = await fetch(`/api/dashboards/${id}`);
        const config = await res.json();
        if (config.error) throw new Error(config.error);
        renderDashboard(config);
    } catch(e) { alert("Error: " + e.message); } 
    finally {
        if(loader) {
            loader.classList.add("hidden");
            loader.classList.remove("flex");
        }
    }
}

// --- UTILS ---
function openFullscreen() {
    if (!currentDashId) return;
    window.open(`/view/${currentDashId}`, '_blank');
}

function resetView() {
    currentDashId = null;
    activeFilters = {};
    mapInstances = {};
    pieColorMap = {};
    document.getElementById("inputSection").classList.remove("hidden");
    document.getElementById("dashboardGrid").classList.add("hidden");
    document.getElementById("pageTitle").innerHTML = `<span class="bg-indigo-100 text-indigo-700 p-1 rounded">📊</span> Nuevo Análisis`;
    const btnFull = document.getElementById("btnFullscreen");
    if(btnFull) btnFull.classList.add("hidden");
    
    const mainScroll = document.getElementById("mainScroll");
    if(mainScroll) mainScroll.classList.replace("p-4", "p-6");
}

async function applyFilter(column, value) {
    if (!currentDashId) return;

    if (activeFilters[column] === value) delete activeFilters[column]; 
    else activeFilters[column] = value; 

    const grid = document.getElementById("dashboardGrid");
    grid.style.opacity = "0.7";

    try {
        const res = await fetch(`/api/dashboards/${currentDashId}/filter`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ filters: activeFilters })
        });
        
        const data = await res.json();
        updateComponentsData(data.components);
        renderFilterTags();

    } catch(e) {
        console.error(e);
        alert("Error al filtrar");
    } finally {
        grid.style.opacity = "1";
    }
}

// --- FUNCIÓN CORREGIDA: ETIQUETAS DE FILTRO ---
function renderFilterTags() {
    let tagContainer = document.getElementById("filterTags");
    if (!tagContainer) {
        tagContainer = document.createElement("div");
        tagContainer.id = "filterTags";
        // CORRECCIÓN: flex-wrap, justify-start y w-full aseguran flujo horizontal
        tagContainer.className = "flex flex-wrap gap-2 mb-2 px-1 w-full justify-start items-center";
        const grid = document.getElementById("dashboardGrid");
        if(grid) grid.parentNode.insertBefore(tagContainer, grid);
    }
    
    tagContainer.innerHTML = "";
    Object.entries(activeFilters).forEach(([col, val]) => {
        const tag = document.createElement("div"); // Cambiado a div para mejor control flex
        // CORRECCIÓN: w-fit, inline-flex y max-w-full
        tag.className = "bg-indigo-600 text-white text-[10px] font-bold px-3 py-1 rounded-full inline-flex items-center gap-2 shadow-sm animate-pulse cursor-pointer hover:bg-red-500 transition w-fit max-w-full";
        // Truncar texto interno si es excesivamente largo
        tag.innerHTML = `<span class="truncate max-w-[200px]">${col}: ${val}</span> <span class="text-[9px]">✕</span>`;
        tag.onclick = () => applyFilter(col, val);
        tagContainer.appendChild(tag);
    });
}

// --- RENDERIZADO COMPACTO ---
function renderDashboard(config) {
    const mainContainer = document.getElementById("dashboardGrid");
    mainContainer.innerHTML = "";
    mainContainer.classList.remove("hidden");
    mainContainer.className = "flex flex-col gap-3 h-full"; 

    const mainScroll = document.getElementById("mainScroll");
    if(mainScroll) {
        mainScroll.classList.remove("p-6", "md:p-10");
        mainScroll.classList.add("p-4");
    }

    document.getElementById("pageTitle").innerHTML = `<span class="bg-indigo-100 text-indigo-700 p-1 rounded">📊</span> <span class="truncate text-base">${config.title || "Dashboard"}</span>`;
    
    const oldTags = document.getElementById("filterTags");
    if(oldTags) oldTags.innerHTML = "";

    const maps = config.components.filter(c => c.type === 'map');
    const kpis = config.components.filter(c => c.type === 'kpi');
    const charts = config.components.filter(c => c.type === 'chart');

    // SECCIÓN SUPERIOR: 42vh
    if (maps.length > 0) {
        const topSection = document.createElement("div");
        topSection.className = "grid grid-cols-1 lg:grid-cols-4 gap-3 h-auto lg:h-[42vh] shrink-0"; 
        
        const mapComp = maps[0];
        const mapCard = document.createElement("div");
        mapCard.className = "lg:col-span-3 bg-white p-1 rounded-2xl shadow-sm border border-slate-200 h-[300px] lg:h-full relative overflow-hidden";
        
        const mapId = "map_" + mapComp.id;
        mapCard.innerHTML = `<div id="${mapId}" class="w-full h-full rounded-xl bg-slate-100 relative"></div>`;
        topSection.appendChild(mapCard);
        
        const kpiCol = document.createElement("div");
        kpiCol.className = "lg:col-span-1 flex flex-col gap-3 h-full";
        
        kpis.forEach(kpi => {
            const kpiCard = createKpiCard(kpi);
            kpiCard.classList.add("flex-grow"); 
            kpiCol.appendChild(kpiCard);
        });
        topSection.appendChild(kpiCol);
        
        mainContainer.appendChild(topSection);
        setTimeout(() => initMap(mapId, mapComp), 100);

    } else {
        if (kpis.length > 0) {
            const kpiRow = document.createElement("div");
            kpiRow.className = "grid grid-cols-1 md:grid-cols-2 gap-3 shrink-0"; 
            kpis.forEach(kpi => {
                const card = createKpiCard(kpi);
                card.classList.add("h-24"); 
                kpiRow.appendChild(card);
            });
            mainContainer.appendChild(kpiRow);
        }
    }

    // SECCIÓN INFERIOR: 38vh
    if (charts.length > 0) {
        const chartGrid = document.createElement("div");
        const heightClass = maps.length > 0 ? "lg:h-[38vh]" : "lg:h-[60vh]";
        chartGrid.className = `grid grid-cols-1 lg:grid-cols-2 gap-3 h-auto ${heightClass} shrink-0`;
        
        charts.forEach((comp, idx) => {
            const card = document.createElement("div");
            card.className = "bg-white p-4 rounded-2xl shadow-sm border border-slate-200 h-[300px] lg:h-full flex flex-col relative";
            
            const headerHtml = `<div class="mb-1"><h3 class="font-bold text-slate-700 text-sm leading-tight truncate" title="${comp.title}">${comp.title}</h3></div>`;
            const chartId = "chart_" + comp.id;
            card.innerHTML = headerHtml + `<div id="${chartId}" class="flex-grow w-full h-full"></div>`;
            
            if(activeFilters[comp.config.x]) card.classList.add("ring-2", "ring-indigo-500");
            
            chartGrid.appendChild(card);
            setTimeout(() => initChart(chartId, comp, idx), 50);
        });
        mainContainer.appendChild(chartGrid);
    }

    const btnFull = document.getElementById("btnFullscreen");
    if(btnFull) btnFull.classList.remove("hidden");

    setTimeout(autoFitText, 0);
}

function createKpiCard(comp) {
    const card = document.createElement("div");
    card.className = "bg-white p-4 rounded-2xl shadow-sm border border-slate-200 flex flex-col justify-center items-center text-center hover:shadow-md transition overflow-hidden min-h-0";
    
    const formattedValue = formatNumber(comp.data.value);
    
    card.innerHTML = `
        <h3 class="font-bold text-slate-400 text-xs uppercase tracking-wider mb-1 truncate w-full px-1" title="${comp.title}">
            ${comp.title}
        </h3>
        
        <div id="kpi_val_${comp.id}" 
             class="kpi-fit-text font-extrabold text-slate-800 tracking-tight w-full px-1 whitespace-nowrap overflow-hidden"
             style="font-size: 36px; line-height: 1;">
            ${formattedValue}
        </div>
        
        ${comp.description ? `<p class="text-[10px] text-slate-400 mt-1 truncate w-full px-2">${comp.description}</p>` : ''}
    `;
    return card;
}

function autoFitText() {
    const elements = document.querySelectorAll('.kpi-fit-text');
    elements.forEach(el => {
        let size = 42; 
        el.style.fontSize = size + 'px';
        while (el.scrollWidth > el.clientWidth && size > 12) {
            size -= 2; 
            el.style.fontSize = size + 'px';
        }
    });
}

function updateComponentsData(components) {
    components.forEach(comp => {
        if (comp.type === 'chart') {
            const chartInstance = echarts.getInstanceByDom(document.getElementById("chart_" + comp.id));
            if (chartInstance) {
                chartInstance.setOption({ dataset: { source: comp.data.source } });
            }
        } else if (comp.type === 'kpi') {
            const kpiValEl = document.getElementById("kpi_val_" + comp.id);
            if (kpiValEl) {
                kpiValEl.innerText = formatNumber(comp.data.value);
                kpiValEl.style.fontSize = "36px";
            }
        } else if (comp.type === 'map') {
             const map = mapInstances[comp.id];
             if (map && map.getSource('points')) {
                 const newGeoJSON = createGeoJSON(comp.data, comp.config);
                 map.getSource('points').setData(newGeoJSON);
             } else {
                 const mapId = "map_" + comp.id;
                 const mapContainer = document.getElementById(mapId);
                 if (mapContainer) {
                     mapContainer.innerHTML = ""; 
                     initMap(mapId, comp); 
                 }
             }
        }
    });
    setTimeout(autoFitText, 0);
}

function createGeoJSON(data, config) {
    const latCol = config.lat;
    const lonCol = config.lon;
    const features = data.map(row => {
        const lat = parseFloat(row[latCol]);
        const lon = parseFloat(row[lonCol]);
        if (isNaN(lat) || isNaN(lon)) return null;
        let popupContent = `<div class="p-1 font-sans">`;
        Object.entries(row).forEach(([k, v]) => {
            if(k !== latCol && k !== lonCol) popupContent += `<span class="text-[10px] text-slate-600 block"><b>${k}:</b> ${v}</span>`;
        });
        popupContent += "</div>";
        return {
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [lon, lat] },
            properties: { description: popupContent }
        };
    }).filter(f => f !== null);
    return { type: 'FeatureCollection', features: features };
}

function formatNumber(val) {
    if (typeof val === 'number') {
        return new Intl.NumberFormat('es-ES', { maximumFractionDigits: 2 }).format(val);
    }
    return val;
}

function initChart(domId, comp, idx) {
    const dom = document.getElementById(domId);
    if (!dom) return;
    const myChart = echarts.init(dom);
    const isPie = comp.chart_type === 'pie';
    
    const colors = [
        '#6366f1', '#10b981', '#f59e0b', '#ec4899', 
        '#3b82f6', '#8b5cf6', '#ef4444', '#06b6d4'
    ];
    const themeColor = colors[idx % colors.length];

    if (isPie) {
        if (!pieColorMap[comp.id]) pieColorMap[comp.id] = {};
        let nextColorIdx = Object.keys(pieColorMap[comp.id]).length;
        const catField = comp.data.dimensions[0]; 
        comp.data.source.forEach(row => {
            const name = row[catField];
            if (!pieColorMap[comp.id][name]) {
                pieColorMap[comp.id][name] = colors[nextColorIdx % colors.length];
                nextColorIdx++;
            }
        });
    }

    const option = {
        color: isPie ? colors : [themeColor],
        tooltip: { 
            trigger: isPie ? 'item' : 'axis', 
            backgroundColor: 'rgba(255,255,255,0.95)', 
            padding: 8,
            textStyle: { color: '#1e293b', fontSize: 11 },
            valueFormatter: (value) => formatNumber(value)
        },
        grid: { left: '2%', right: '3%', bottom: '2%', top: '12%', containLabel: true },
        dataset: { dimensions: comp.data.dimensions, source: comp.data.source },
        xAxis: isPie ? { show: false } : { 
            type: 'category', 
            axisLabel: { rotate: 0, fontSize: 10, color: '#64748b', interval: 'auto' },
            axisTick: { show: false },
            axisLine: { lineStyle: { color: '#e2e8f0' } }
        },
        yAxis: isPie ? { show: false } : { 
            type: 'value', 
            splitLine: { lineStyle: { type: 'dashed', color: '#f1f5f9' } },
            axisLabel: { fontSize: 10, color: '#94a3b8' }
        },
        series: [{
            type: comp.chart_type || 'bar',
            radius: isPie ? ['45%', '75%'] : undefined,
            center: isPie ? ['50%', '50%'] : undefined,
            itemStyle: { 
                borderRadius: isPie ? 4 : [3, 3, 0, 0],
                borderColor: '#fff',
                borderWidth: isPie ? 1 : 0,
                color: isPie ? (params) => pieColorMap[comp.id][params.name] || themeColor : themeColor
            },
            label: { 
                show: isPie, 
                position: 'outside',
                formatter: '{b}',
                fontSize: 10,
                color: '#64748b' 
            },
            labelLine: { show: isPie, length: 10, length2: 10 }
        }]
    };
    myChart.setOption(option);
    
    myChart.on('click', function(params) {
        if (comp.config && comp.config.x && params.name !== 'Otros') {
            applyFilter(comp.config.x, params.name);
        }
    });
    
    new ResizeObserver(() => myChart.resize()).observe(dom);
}

window.addEventListener("resize", () => {
    document.querySelectorAll('div[id^="chart_"]').forEach(el => {
        const instance = echarts.getInstanceByDom(el);
        if (instance) instance.resize();
    });
    autoFitText();
});

function initMap(domId, comp) {
    const dom = document.getElementById(domId);
    if (!dom) return;
    const geoJSON = createGeoJSON(comp.data, comp.config);
    if (geoJSON.features.length === 0) {
        dom.innerHTML = "<div class='flex items-center justify-center h-full text-xs text-slate-400'>Sin coordenadas</div>";
        return;
    }
    const bounds = new maplibregl.LngLatBounds();
    geoJSON.features.forEach(feature => bounds.extend(feature.geometry.coordinates));
    
    const map = new maplibregl.Map({
        container: domId,
        style: {
            version: 8,
            sources: {
                'osm': {
                    type: 'raster',
                    tiles: ['https://a.tile.openstreetmap.org/{z}/{x}/{y}.png'],
                    tileSize: 256,
                    attribution: ''
                }
            },
            layers: [{
                id: 'osm', type: 'raster', source: 'osm', minzoom: 0, maxzoom: 18
            }]
        },
        bounds: bounds,
        fitBoundsOptions: { padding: 40, maxZoom: 14 }
    });
    mapInstances[comp.id] = map;
    map.on('load', () => {
        map.addSource('points', { type: 'geojson', data: geoJSON });
        map.addLayer({
            id: 'points-layer',
            type: 'circle',
            source: 'points',
            paint: {
                'circle-radius': 5,
                'circle-color': '#4f46e5',
                'circle-stroke-width': 1,
                'circle-stroke-color': '#ffffff',
                'circle-opacity': 0.8
            }
        });
        map.on('click', 'points-layer', (e) => {
            const coordinates = e.features[0].geometry.coordinates.slice();
            const description = e.features[0].properties.description;
            while (Math.abs(e.lngLat.lng - coordinates[0]) > 180) {
                coordinates[0] += e.lngLat.lng > coordinates[0] ? 360 : -360;
            }
            new maplibregl.Popup().setLngLat(coordinates).setHTML(description).addTo(map);
        });
        map.on('mouseenter', 'points-layer', () => map.getCanvas().style.cursor = 'pointer');
        map.on('mouseleave', 'points-layer', () => map.getCanvas().style.cursor = '');
    });
}