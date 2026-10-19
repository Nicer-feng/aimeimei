import SwiftUI

struct LoginView: View {
    let store: AppStore
    @State private var username = ""
    @State private var password = ""
    @State private var answer = ""
    @FocusState private var focused: Field?
    private enum Field { case username, password, captcha }
    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                VStack(spacing: 12) {
                    Image("Avatar").resizable().scaledToFit().frame(width: 88, height: 88).accessibilityHidden(true)
                    Text("你好，我是槑槑").font(.largeTitle.bold())
                    Text("用熟悉的账号，继续你的想法").foregroundStyle(.secondary)
                }.padding(.top, 44)
                VStack(spacing: 16) {
                    TextField("用户名", text: $username).textContentType(.username)
                        .textInputAutocapitalization(.never).autocorrectionDisabled().focused($focused, equals: .username)
                        .submitLabel(.next).onSubmit { focused = .password }.accessibilityIdentifier("usernameField")
                    SecureField("密码", text: $password).textContentType(.password).focused($focused, equals: .password)
                        .submitLabel(.next).onSubmit { focused = .captcha }.accessibilityIdentifier("passwordField")
                    HStack(spacing: 12) {
                        TextField("图形验证码", text: $answer).textInputAutocapitalization(.characters)
                            .autocorrectionDisabled().focused($focused, equals: .captcha)
                            .submitLabel(.go).onSubmit { login() }.accessibilityIdentifier("captchaField")
                        Button {
                            answer = ""; Task { await store.refreshCaptcha() }
                        } label: {
                            if let captcha = store.captcha { CaptchaImage(svg: captcha.svg) }
                            else { Label("获取验证码", systemImage: "arrow.clockwise").font(.caption) }
                        }.buttonStyle(.plain).accessibilityLabel("刷新图形验证码")
                    }
                }.textFieldStyle(.roundedBorder)
                if let error = store.error { ErrorNotice(text: error) }
                Button(action: login) {
                    HStack { if store.busy { ProgressView().tint(.white) }; Text("登录槑槑").fontWeight(.semibold) }
                        .frame(maxWidth: .infinity).padding(.vertical, 7)
                }.buttonStyle(.borderedProminent).controlSize(.large)
                    .disabled(store.busy || username.isEmpty || password.isEmpty || answer.isEmpty || store.captcha == nil)
                    .accessibilityIdentifier("loginButton")
                if store.captcha == nil {
                    Button("重新连接") { Task { await store.start() } }.disabled(store.busy)
                }
                Text("账号由现有槑槑后台管理，密码不会保存在本机。").font(.footnote).foregroundStyle(.secondary)
                #if DEBUG
                if ProcessInfo.processInfo.arguments.contains("--ui-testing") {
                    Text("离线界面验收 · 不连接真实服务").font(.caption).foregroundStyle(.secondary)
                }
                #endif
            }.padding(.horizontal, 28).padding(.bottom, 30).frame(maxWidth: 480)
                .frame(maxWidth: .infinity)
        }
        .background(Brand.background).scrollDismissesKeyboard(.interactively)
        .disabled(store.busy)
    }
    private func login() {
        guard !username.isEmpty, !password.isEmpty, !answer.isEmpty, !store.busy else { return }
        focused = nil
        let value = password
        password = ""
        Task { await store.login(username: username, password: value, answer: answer); answer = "" }
    }
}
