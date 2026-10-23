import SwiftUI

struct LoginView: View {
    let store: AppStore
    @State private var username = ""
    @State private var password = ""
    @State private var answer = ""
    @State private var code = ""
    @State private var mode: Mode = .password
    @State private var now = Date()
    @FocusState private var focused: Field?
    private enum Field { case username, password, captcha, phone, code }
    private enum Mode: String { case password, sms }
    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                VStack(spacing: 12) {
                    Image("Avatar").resizable().scaledToFit().frame(width: 88, height: 88).clipShape(RoundedRectangle(cornerRadius: 24)).accessibilityHidden(true)
                    Text("你好，我是槑槑").font(.largeTitle.bold())
                    Text("用熟悉的账号，继续你的想法").foregroundStyle(.secondary)
                }.padding(.top, 44)
                if store.smsConfig?.available == true {
                    Picker("登录方式", selection: $mode) {
                        Text("账号密码").tag(Mode.password)
                        Text("短信验证码").tag(Mode.sms)
                    }.pickerStyle(.segmented).accessibilityIdentifier("loginModePicker")
                }
                VStack(spacing: 16) {
                    if mode == .password {
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
                    } else {
                        TextField("已绑定的手机号", text: Binding(get: { store.smsLogin.phone }, set: { store.setLoginPhone($0) }))
                            .keyboardType(.phonePad).textContentType(.telephoneNumber)
                            .focused($focused, equals: .phone).accessibilityIdentifier("phoneField")
                        HStack(spacing: 12) {
                            TextField("6 位短信验证码", text: $code).keyboardType(.numberPad).textContentType(.oneTimeCode)
                                .focused($focused, equals: .code).accessibilityIdentifier("smsCodeField")
                                .onChange(of: code) { _, value in
                                    code = String(value.filter { $0 >= "0" && $0 <= "9" }.prefix(6))
                                }
                            Button(store.smsLogin.remaining(at: now) > 0 ? "\(store.smsLogin.remaining(at: now)) 秒后重发" : "获取验证码") {
                                code = ""; focused = nil
                                Task {
                                    await store.sendLoginSMS()
                                    if store.smsLogin.challenge != nil { focused = .code }
                                }
                            }.font(.subheadline).buttonStyle(.bordered)
                                .disabled(store.busy || !store.smsLogin.canSend(at: now))
                                .accessibilityIdentifier("sendSMSButton")
                        }
                        Text("仅限后台已绑定并启用的中国大陆手机号，不会自动注册账号。")
                            .font(.footnote).foregroundStyle(.secondary).frame(maxWidth: .infinity, alignment: .leading)
                    }
                }.textFieldStyle(.roundedBorder)
                if let error = store.error { ErrorNotice(text: error) }
                if mode == .sms, let notice = store.loginNotice {
                    Text(notice).font(.footnote).foregroundStyle(.secondary).accessibilityIdentifier("smsNotice")
                }
                Button(action: login) {
                    HStack { if store.busy { ProgressView().tint(.white) }; Text("登录槑槑").fontWeight(.semibold) }
                        .frame(maxWidth: .infinity).padding(.vertical, 7)
                }.buttonStyle(.borderedProminent).controlSize(.large)
                    .disabled(store.busy || (mode == .password
                        ? username.isEmpty || password.isEmpty || answer.isEmpty || store.captcha == nil
                        : !store.smsLogin.canVerify(code: code, at: now)))
                    .accessibilityIdentifier("loginButton")
                if mode == .password && store.captcha == nil {
                    Button("重新连接") { Task { await store.start() } }.disabled(store.busy)
                }
                Text("账号由现有槑槑后台管理，密码和短信验证码不会保存在本机。").font(.footnote).foregroundStyle(.secondary)
                #if DEBUG
                if ProcessInfo.processInfo.arguments.contains("--ui-testing") {
                    Text("离线界面验收 · 不连接真实服务").font(.caption).foregroundStyle(.secondary)
                }
                #endif
            }.padding(.horizontal, 28).padding(.bottom, 30).frame(maxWidth: 480)
                .frame(maxWidth: .infinity)
        }
        .background(Brand.background).scrollDismissesKeyboard(.interactively)
        .task { await store.loadSMSConfigurationIfNeeded() }
        .onReceive(Timer.publish(every: 1, on: .main, in: .common).autoconnect()) { now = $0 }
        .onChange(of: store.smsLogin.phone) { _, _ in code = "" }
        .onChange(of: mode) { _, _ in
            focused = nil; password = ""; answer = ""; code = ""; store.clearLoginFeedback()
            if mode == .password && store.captcha == nil { Task { await store.refreshCaptcha() } }
        }
        .disabled(store.busy)
    }
    private func login() {
        guard !store.busy else { return }
        if mode == .sms {
            guard store.smsLogin.canVerify(code: code) else { return }
            focused = nil
            let value = code; code = ""
            Task { await store.loginSMS(code: value) }
            return
        }
        guard !username.isEmpty, !password.isEmpty, !answer.isEmpty else { return }
        focused = nil
        let value = password
        password = ""
        Task { await store.login(username: username, password: value, answer: answer); answer = "" }
    }
}
