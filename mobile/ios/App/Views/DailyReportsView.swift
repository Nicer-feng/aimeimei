import SwiftUI
import MeimeiCore

struct DailyReportsView: View {
    let controller: DailyReportsController
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 24) {
                        if let notice = controller.notificationNotice { ErrorNotice(text: notice) }
                        if let error = controller.error {
                            ErrorNotice(text: error)
                            Button("重试", systemImage: "arrow.clockwise") { Task { await controller.refresh() } }
                        }
                        if controller.reports.isEmpty && !controller.busy && controller.error == nil {
                            ContentUnavailableView("暂无日报", systemImage: "doc.text")
                        }
                        ForEach(controller.reports) { report in
                            VStack(alignment: .leading, spacing: 12) {
                                HStack(spacing: 10) {
                                    Image("Avatar").resizable().scaledToFit().frame(width: 32, height: 32)
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text("槑槑 · 前端研发日报").font(.subheadline.bold())
                                        Text(report.reportDate + (report.simulation ? " · 模拟" : "")).font(.caption).foregroundStyle(.secondary)
                                    }
                                    Spacer()
                                    if report.readAt == 0 { Image(systemName: "circle.fill").font(.system(size: 7)).foregroundStyle(Brand.accent) }
                                }
                                MarkdownView(content: report.content).padding(14)
                                    .background(Brand.background, in: RoundedRectangle(cornerRadius: 8))
                            }.id(report.id).accessibilityIdentifier("dailyReport-\(report.id)")
                                .task { await controller.read(report) }
                        }
                        if controller.nextBefore != nil {
                            Button("更早的日报", systemImage: "clock.arrow.circlepath") { Task { await controller.refresh(older: true) } }.disabled(controller.busy)
                        }
                        if controller.busy { ProgressView().frame(maxWidth: .infinity) }
                    }.padding(20)
                }
                .refreshable { await controller.refresh() }
                .task {
                    await controller.refresh()
                    if let id = controller.focusID { proxy.scrollTo(id, anchor: .top) }
                }
                .onChange(of: controller.focusID) { _, id in
                    Task { await controller.refresh(); if let id { proxy.scrollTo(id, anchor: .top) } }
                }
            }
            .navigationTitle("前端研发日报").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
        }
    }
}
