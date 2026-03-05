/**
 * 多光谱图像分析系统 - 主应用
 */
import React, { useState, useEffect, useMemo } from 'react';
import { Layout, Button, message, Tree, Tabs, Popconfirm, Select } from 'antd';
import { DeleteOutlined, PictureOutlined, FolderOutlined, FileImageOutlined, ImportOutlined } from '@ant-design/icons';
import type { DataNode } from 'antd/es/tree';
import { batchService, imageService } from './services/api';
import type { BatchInfo, BandType, ImageInfo, BatchImageInfo } from './types';
import { BAND_TYPES, BAND_LABELS } from './types';
import { ImageViewer, ToolPanel, BlendPanel, VegetationPanel, AlignmentPanel, BatchImportDialog } from './components';
import ROICanvas, { type ROICoords } from './components/ROICanvas';
import './App.css';

const { Header, Content, Sider } = Layout;

// 通道类型
type ChannelType = 'rgb' | 'r' | 'g' | 'b';

interface SelectedNode {
    batchId: string;
    bandType: BandType;
    channel: ChannelType;
    image: ImageInfo | null;
    imageType: 'source' | 'aligned';  // 标识选中的是 source 还是 aligned 图像
}

function _adaptBatchImage(img: any): ImageInfo {
    return {
        id: img.id,
        filename: img.filename,
        filepath: img.filepath,
        url: img.url,
        size: img.size,
        width: img.width,
        height: img.height,
        channels: img.channels,
        upload_time: img.upload_time
    };
}

function App() {
    const [batches, setBatches] = useState<BatchInfo[]>([]);
    const [images, setImages] = useState<ImageInfo[]>([]); // 保留用于兼容其他面板
    const [selectedNode, setSelectedNode] = useState<SelectedNode | null>(null);
    const [pixelPosition, setPixelPosition] = useState<{ x: number; y: number } | null>(null);
    const [activePanel, setActivePanel] = useState('tool');
    const [expandedKeys, setExpandedKeys] = useState<string[]>([]);
    const [sortBy, setSortBy] = useState<'name' | 'time'>('time'); // 排序方式
    const [blendedImageUrl, setBlendedImageUrl] = useState<string | null>(null); // 混合预览图
    const [importDialogOpen, setImportDialogOpen] = useState(false);

    // ROI 绘制模式
    const [roiDrawMode, setRoiDrawMode] = useState(false);
    const [currentRoi, setCurrentRoi] = useState<ROICoords | null>(null);

    // ESC 退出绘制模式
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if (e.key === 'Escape' && roiDrawMode) setRoiDrawMode(false);
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [roiDrawMode]);

    // 图像处理状态
    const [colormap, setColormap] = useState('gray'); // 色带
    const [whiteBalance, setWhiteBalance] = useState({ r: 1, g: 1, b: 1 }); // 白平衡
    const [saturation, setSaturation] = useState(1); // 饱和度
    const [histogram, setHistogram] = useState<{ r: number[], g: number[], b: number[] } | null>(null); // 直方图

    // 拖拽调整大小状态
    const [leftWidth, setLeftWidth] = useState(280);
    const [rightWidth, setRightWidth] = useState(320);
    const [isResizingLeft, setIsResizingLeft] = useState(false);
    const [isResizingRight, setIsResizingRight] = useState(false);

    useEffect(() => {
        const handleMouseMove = (e: MouseEvent) => {
            if (isResizingLeft) {
                // 限制左侧宽度范围 200-500
                const newWidth = Math.max(200, Math.min(e.clientX, 500));
                setLeftWidth(newWidth);
            }
            if (isResizingRight) {
                // 限制右侧宽度范围 250-600
                const newWidth = Math.max(250, Math.min(window.innerWidth - e.clientX, 600));
                setRightWidth(newWidth);
            }
        };

        const handleMouseUp = () => {
            setIsResizingLeft(false);
            setIsResizingRight(false);
        };

        if (isResizingLeft || isResizingRight) {
            document.addEventListener('mousemove', handleMouseMove);
            document.addEventListener('mouseup', handleMouseUp);
            document.body.style.userSelect = 'none';
            document.body.style.cursor = 'col-resize';
        } else {
            document.body.style.userSelect = '';
            document.body.style.cursor = '';
        }

        return () => {
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('mouseup', handleMouseUp);
            document.body.style.userSelect = '';
            document.body.style.cursor = '';
        };
    }, [isResizingLeft, isResizingRight]);

    useEffect(() => {
        loadBatches();
        loadImages(); // 继续加载单独图像用于兼容
    }, []);

    const loadBatches = async () => {
        try {
            const data = await batchService.listBatches();
            setBatches(data);
        } catch (error) {
            message.error('加载批次列表失败');
        }
    };

    const loadImages = async () => {
        try {
            const data = await imageService.listImages();
            setImages(data);
        } catch (error) {
            // 静默失败，主要使用批次数据
        }
    };

    const handleDeleteBatch = async (batchId: string) => {
        try {
            await batchService.deleteBatch(batchId);
            message.success('批次删除成功');
            await loadBatches();
            if (selectedNode?.batchId === batchId) {
                setSelectedNode(null);
            }
        } catch (error) {
            message.error('删除失败');
        }
    };

    const handlePixelHover = (x: number, y: number) => {
        setPixelPosition({ x, y });
    };

    // 从批次中收集所有图像用于其他面板
    const allImages = useMemo(() => {
        const imgs: ImageInfo[] = [];
        batches.forEach(batch => {
            BAND_TYPES.forEach(band => {
                const img = batch.images[band];
                if (img) {
                    imgs.push({
                        id: img.id,
                        filename: img.filename,
                        filepath: img.filepath,
                        url: img.url,
                        size: img.size,
                        width: img.width,
                        height: img.height,
                        channels: img.channels,
                        upload_time: img.upload_time
                    });
                }
            });
        });
        // 合并单独上传的图像
        images.forEach(img => {
            if (!imgs.find(i => i.id === img.id)) {
                imgs.push(img);
            }
        });
        return imgs;
    }, [batches, images]);

    // 构建树形数据
    const treeData: DataNode[] = useMemo(() => {
        // 根据选择的排序方式排序批次
        const sortedBatches = [...batches].sort((a: BatchInfo, b: BatchInfo) => {
            if (sortBy === 'name') {
                return a.name.localeCompare(b.name, 'zh-CN');
            } else {
                // 按时间降序（最新的在前）
                return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
            }
        });

        // 辅助函数：生成波段节点
        const generateBandNodes = (batchId: string, prefix: string, imagesMap: Record<string, any> = {}) => {
            return BAND_TYPES.map(band => {
                const img = imagesMap[band];
                const nodeKey = `${batchId}-${prefix}-${band}`;

                if (img) {
                    return {
                        key: nodeKey,
                        title: (
                            <div className={`channel-node ${img ? 'has-image' : 'no-image'}`}>
                                <FileImageOutlined />
                                <span>{BAND_LABELS[band]}</span>
                                {img && <span className="file-name">({img.filename})</span>}
                            </div>
                        ),
                        children: [
                            {
                                key: `${nodeKey}-rgb`,
                                title: <span className="sub-channel-node">全彩影像</span>,
                                isLeaf: true,
                            },
                            {
                                key: `${nodeKey}-r`,
                                title: <span className="sub-channel-node">R 通道 (灰度)</span>,
                                isLeaf: true,
                            },
                            {
                                key: `${nodeKey}-g`,
                                title: <span className="sub-channel-node">G 通道 (灰度)</span>,
                                isLeaf: true,
                            },
                            {
                                key: `${nodeKey}-b`,
                                title: <span className="sub-channel-node">B 通道 (灰度)</span>,
                                isLeaf: true,
                            }
                        ]
                    };
                }

                return {
                    key: nodeKey,
                    title: (
                        <span className={`channel-node no-image`}>
                            <FileImageOutlined />
                            <span>{BAND_LABELS[band]}</span>
                        </span>
                    ),
                    isLeaf: true,
                    disabled: true,
                };
            });
        };

        return sortedBatches.map((batch: BatchInfo) => {
            // 计算已有图像数量
            // 兼容旧数据 images，以及新数据 source_images/aligned_images
            const sourceImgs = batch.source_images || batch.images || ({} as Record<string, BatchImageInfo | null>);
            const alignedImgs = batch.aligned_images || ({} as Record<string, BatchImageInfo | null>);

            const sourceCount = BAND_TYPES.filter(band => sourceImgs[band] !== null && sourceImgs[band] !== undefined).length;
            const alignedCount = BAND_TYPES.filter(band => alignedImgs[band] !== null && alignedImgs[band] !== undefined).length;
            const totalCount = sourceCount + alignedCount;

            return {
                key: batch.id,
                title: (
                    <div className="tree-node-title">
                        <FolderOutlined />
                        <span className="node-name">{batch.name}</span>
                        <span className="node-size">{totalCount} items</span>
                        <Popconfirm
                            title="确定删除此批次及其所有图像?"
                            onConfirm={() => handleDeleteBatch(batch.id)}
                            okText="确定"
                            cancelText="取消"
                        >
                            <Button
                                size="small"
                                danger
                                type="text"
                                icon={<DeleteOutlined />}
                                onClick={(e) => e.stopPropagation()}
                                className="delete-btn"
                            />
                        </Popconfirm>
                    </div>
                ),
                children: [
                    {
                        key: `${batch.id}-source`,
                        title: (
                            <div className="tree-node-title">
                                <FolderOutlined />
                                <span>Source</span>
                                <span className="node-size" style={{ fontSize: '10px', marginLeft: 4 }}>({sourceCount})</span>
                            </div>
                        ),
                        children: generateBandNodes(batch.id, 'source', sourceImgs)
                    },
                    {
                        key: `${batch.id}-aligned`,
                        title: (
                            <div className="tree-node-title">
                                <FolderOutlined />
                                <span>Aligned</span>
                                <span className="node-size" style={{ fontSize: '10px', marginLeft: 4 }}>({alignedCount})</span>
                            </div>
                        ),
                        children: generateBandNodes(batch.id, 'aligned', alignedImgs)
                    }
                ]
            };
        });
    }, [batches, sortBy]);

    // 处理树节点选择
    const handleTreeSelect = (selectedKeys: React.Key[]) => {
        setBlendedImageUrl(null); // 切换图片时清除混合图层
        if (selectedKeys.length === 0) return;

        const key = selectedKeys[0] as string;

        // Key formats:
        // Batch: UUID
        // Folder: UUID-source | UUID-aligned
        // Band: UUID-source-BAND | UUID-aligned-BAND
        // Leaf: UUID-source-BAND-CHANNEL | UUID-aligned-BAND-CHANNEL

        // Check for Batch UUID
        const batch = batches.find((b: BatchInfo) => b.id === key);
        if (batch) {
            // Selected a batch node directly -> Show RGB from source if available
            const sourceImgs = batch.source_images || batch.images || ({} as Record<string, BatchImageInfo | null>);
            const img = sourceImgs['rgb'];
            if (img) {
                setSelectedNode({
                    batchId: batch.id,
                    bandType: 'rgb',
                    channel: 'rgb',
                    image: _adaptBatchImage(img),
                    imageType: 'source'
                });
            }
            return;
        }

        // Parse key
        // Find matching batch by simple prefix match is risky due to source/aligned dash
        // But batch IDs are UUIDs.

        let matchedBatch: BatchInfo | undefined;
        let suffix = "";

        for (const b of batches) {
            if (key.startsWith(b.id + '-')) {
                matchedBatch = b;
                suffix = key.substring(b.id.length + 1);
                break;
            }
        }

        if (!matchedBatch) return;

        // suffix could be: "source", "aligned", "source-rgb", "source-rgb-r", etc.
        const parts = suffix.split('-');
        const folderType = parts[0]; // "source" or "aligned"

        if (folderType !== 'source' && folderType !== 'aligned') return;

        const imgMap = folderType === 'source'
            ? (matchedBatch.source_images || matchedBatch.images || ({} as Record<string, BatchImageInfo | null>))
            : (matchedBatch.aligned_images || ({} as Record<string, BatchImageInfo | null>));

        if (parts.length === 1) {
            // Selected "Source" or "Aligned" folder
            // Maybe select first available image in that folder?
            // For now, do nothing or select RGB
            const img = imgMap['rgb'];
            if (img) {
                setSelectedNode({
                    batchId: matchedBatch.id,
                    bandType: 'rgb',
                    channel: 'rgb',
                    image: _adaptBatchImage(img),
                    imageType: folderType
                });
            }
            return;
        }

        // parts[1] is bandType
        const bandType = parts[1] as BandType;
        if (!BAND_TYPES.includes(bandType)) return;

        const img = imgMap[bandType];

        if (parts.length === 2) {
            // Selected Band Node (e.g. Source -> RGB)
            // Default to rgb channel

            setSelectedNode({
                batchId: matchedBatch.id,
                bandType: bandType,
                channel: 'rgb',
                image: img ? _adaptBatchImage(img) : null,
                imageType: folderType
            });
        } else if (parts.length === 3) {
            // Selected Leaf Node (e.g. Source -> RGB -> R Channel)
            const channel = parts[2] as ChannelType;
            if (['rgb', 'r', 'g', 'b'].includes(channel)) {
                setSelectedNode({
                    batchId: matchedBatch.id,
                    bandType: bandType,
                    channel: channel,
                    image: img ? _adaptBatchImage(img) : null,
                    imageType: folderType
                });
            }
        }
    };

    const handleAlignmentComplete = async () => {
        await loadBatches();
        await loadImages();
    };

    const handleImportSuccess = () => {
        loadBatches();
    };

    // 获取当前选中批次的图像
    const currentBatchImages = useMemo(() => {
        if (!selectedNode?.batchId) return allImages;

        const batch = batches.find(b => b.id === selectedNode.batchId);
        if (!batch) return allImages;

        const imgs: ImageInfo[] = [];
        BAND_TYPES.forEach(band => {
            // Check source
            const sImg = batch.source_images?.[band] || batch.images?.[band];
            if (sImg) imgs.push(_adaptBatchImage(sImg));

            // Check aligned
            const aImg = batch.aligned_images?.[band];
            if (aImg) imgs.push(_adaptBatchImage(aImg));
        });

        return imgs.length > 0 ? imgs : allImages;
    }, [selectedNode, batches, allImages]);

    const tabItems = [
        {
            key: 'tool',
            label: '图像调节',
            children: (
                <ToolPanel
                    image={selectedNode?.image || null}
                    colormap={colormap}
                    onColormapChange={setColormap}
                    whiteBalance={whiteBalance}
                    onWhiteBalanceChange={setWhiteBalance}
                    saturation={saturation}
                    onSaturationChange={setSaturation}
                    histogram={histogram}
                />
            ),
        },
        {
            key: 'alignment',
            label: '图像对齐',
            children: <AlignmentPanel
                images={allImages}
                batch={selectedNode?.batchId ? batches.find((b: BatchInfo) => b.id === selectedNode.batchId) : null}
                batchId={selectedNode?.batchId}
                onAlignmentComplete={handleAlignmentComplete}
                roi={currentRoi}
                onStartDrawROI={() => setRoiDrawMode(true)}
                onClearROI={() => { setCurrentRoi(null); setRoiDrawMode(false); }}
            />,
        },
        {
            key: 'blend',
            label: '光谱混合',
            children: <BlendPanel
                batch={selectedNode?.batchId ? batches.find((b: BatchInfo) => b.id === selectedNode.batchId) : null}
                imageType={selectedNode?.imageType || 'source'}
                pixelPosition={pixelPosition}
                onBlendedImageUrlChange={setBlendedImageUrl}
            />,
        },
        {
            key: 'vegetation',
            label: '植被指数',
            children: <VegetationPanel
                images={currentBatchImages}
                onBlendedImageUrlChange={setBlendedImageUrl}
            />,
        },
    ];

    // 计算批次中的总图像数
    const totalImages = useMemo(() => {
        return batches.reduce((acc, batch) => {
            return acc + BAND_TYPES.filter(band => batch.images[band] !== null).length;
        }, 0);
    }, [batches]);

    return (
        <Layout className="app-layout">
            <Header className="app-header">
                <div className="header-logo">
                    <PictureOutlined />
                    <span>多光谱图像分析系统</span>
                </div>
                <div className="header-info">
                    <span>{batches.length} 个批次 / {totalImages} 张图像</span>
                </div>
            </Header>

            <Layout className="main-layout">
                {/* 左侧批次树 */}
                <Sider width={leftWidth} className="image-sider">
                    <div className="sider-header">
                        <Button
                            icon={<ImportOutlined />}
                            type="primary"
                            block
                            onClick={() => setImportDialogOpen(true)}
                        >
                            导入批次
                        </Button>
                        <Select
                            value={sortBy}
                            onChange={setSortBy}
                            style={{ width: '100%', marginTop: 12 }}
                            options={[
                                { value: 'time', label: '按时间排序' },
                                { value: 'name', label: '按名称排序' }
                            ]}
                        />
                    </div>

                    <div className="image-tree">
                        <Tree
                            treeData={treeData}
                            selectedKeys={selectedNode ?
                                [`${selectedNode.batchId}-${selectedNode.bandType}-${selectedNode.channel}`]
                                : []
                            }
                            expandedKeys={expandedKeys}
                            onExpand={(keys) => setExpandedKeys(keys as string[])}
                            onSelect={handleTreeSelect}
                            showLine={{ showLeafIcon: false }}
                            blockNode
                        />
                    </div>
                </Sider>

                <div
                    className={`resizer-vertical ${isResizingLeft ? 'resizing' : ''}`}
                    onMouseDown={() => setIsResizingLeft(true)}
                />

                {/* 中间图像查看器 */}
                <Content className="viewer-content" style={{ position: 'relative' }}>
                    <ImageViewer
                        image={selectedNode?.image || null}
                        blendedUrl={blendedImageUrl}
                        channel={selectedNode?.channel || 'rgb'}
                        colormap={colormap}
                        whiteBalance={whiteBalance}
                        saturation={saturation}
                        onHistogramChange={setHistogram}
                        onPixelHover={roiDrawMode ? undefined : handlePixelHover}
                    />
                    {roiDrawMode && (
                        <ROICanvas
                            roi={currentRoi}
                            onROIDraw={(r) => {
                                setCurrentRoi(r);
                                setRoiDrawMode(false);
                            }}
                        />
                    )}
                </Content>

                <div
                    className={`resizer-vertical ${isResizingRight ? 'resizing' : ''}`}
                    onMouseDown={() => setIsResizingRight(true)}
                />

                {/* 右侧工具面板 */}
                <Sider width={rightWidth} className="tool-sider">
                    <Tabs
                        items={tabItems}
                        activeKey={activePanel}
                        onChange={setActivePanel}
                        className="panel-tabs"
                    />
                </Sider>
            </Layout>

            {/* 批次导入对话框 */}
            <BatchImportDialog
                open={importDialogOpen}
                onClose={() => setImportDialogOpen(false)}
                onSuccess={handleImportSuccess}
            />
        </Layout>
    );
}



export default App;
