// ============================================================
// LoginPage — 登录 / 注册页面
// ============================================================

import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Form, Input, Button, Tabs, Card, message, Spin } from 'antd';
import { UserOutlined, LockOutlined, MailOutlined } from '@ant-design/icons';
import { useAuth } from '../contexts/AuthContext';

const LoginPage: React.FC = () => {
  const { login, register, isLoading } = useAuth();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<string>('login');
  const [submitting, setSubmitting] = useState(false);

  /** 把后端英文 detail 翻成人话，避免把原始 JSON 甩给用户 */
  const friendlyError = (err: any, fallback: string): string => {
    const raw: string = err?.message || '';
    const map: Record<string, string> = {
      'Incorrect username or password': '用户名或密码错误',
      'Username already registered': '该用户名已被注册，换一个试试',
      'Email already registered': '该邮箱已被注册',
      'User not found or disabled': '账号不存在或已被禁用',
    };
    for (const [k, v] of Object.entries(map)) {
      if (raw.includes(k)) return v;
    }
    if (err?.status === 422) return '提交的格式不对，请检查输入内容';
    if (err?.status >= 500) return '服务端出错了，请稍后重试';
    return raw || fallback;
  };

  /** 登录提交 */
  const handleLogin = async (values: { username: string; password: string }) => {
    setSubmitting(true);
    try {
      await login(values.username, values.password);
      message.success('登录成功！');
      navigate('/', { replace: true });
    } catch (err: any) {
      message.error(friendlyError(err, '登录失败，请重试'));
    } finally {
      setSubmitting(false);
    }
  };

  /** 注册提交 */
  const handleRegister = async (values: { username: string; password: string; confirmPassword: string; email?: string; display_name?: string }) => {
    if (values.password !== values.confirmPassword) {
      message.error('两次输入的密码不一致');
      return;
    }
    setSubmitting(true);
    try {
      await register(values.username, values.password, values.email, values.display_name);
      message.success('注册成功！');
      navigate('/', { replace: true });
    } catch (err: any) {
      message.error(friendlyError(err, '注册失败，请重试'));
    } finally {
      setSubmitting(false);
    }
  };

  // 加载中（校验 token 时）
  if (isLoading) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
        <Spin size="large" tip="正在验证登录状态..." />
      </div>
    );
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
      }}
    >
      <Card
        style={{ width: 420, boxShadow: '0 8px 32px rgba(0,0,0,0.15)' }}
        styles={{ body: { padding: '32px' } }}
      >
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <h1 style={{ fontSize: 24, fontWeight: 600, marginBottom: 4 }}>AI Runtime OS</h1>
          <p style={{ color: '#888' }}>登录以继续使用</p>
        </div>

        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          centered
          items={[
            {
              key: 'login',
              label: '登录',
              children: (
                <Form
                  name="login"
                  layout="vertical"
                  onFinish={handleLogin}
                  autoComplete="off"
                  style={{ marginTop: 16 }}
                >
                  <Form.Item
                    name="username"
                    rules={[{ required: true, message: '请输入用户名' }]}
                  >
                    <Input
                      prefix={<UserOutlined />}
                      placeholder="用户名"
                      size="large"
                    />
                  </Form.Item>

                  <Form.Item
                    name="password"
                    rules={[{ required: true, message: '请输入密码' }]}
                  >
                    <Input.Password
                      prefix={<LockOutlined />}
                      placeholder="密码"
                      size="large"
                    />
                  </Form.Item>

                  <Form.Item style={{ marginTop: 24 }}>
                    <Button
                      type="primary"
                      htmlType="submit"
                      loading={submitting}
                      size="large"
                      block
                    >
                      登录
                    </Button>
                  </Form.Item>
                </Form>
              ),
            },
            {
              key: 'register',
              label: '注册',
              children: (
                <Form
                  name="register"
                  layout="vertical"
                  onFinish={handleRegister}
                  autoComplete="off"
                  style={{ marginTop: 16 }}
                >
                  <Form.Item
                    name="username"
                    rules={[
                      { required: true, message: '请输入用户名' },
                      { min: 3, message: '用户名至少 3 个字符' },
                    ]}
                  >
                    <Input
                      prefix={<UserOutlined />}
                      placeholder="用户名"
                      size="large"
                    />
                  </Form.Item>

                  <Form.Item
                    name="email"
                  >
                    <Input
                      prefix={<MailOutlined />}
                      placeholder="邮箱（可选）"
                      size="large"
                    />
                  </Form.Item>

                  <Form.Item
                    name="display_name"
                  >
                    <Input
                      placeholder="显示名称（可选）"
                      size="large"
                    />
                  </Form.Item>

                  <Form.Item
                    name="password"
                    rules={[
                      { required: true, message: '请输入密码' },
                      { min: 6, message: '密码至少 6 个字符' },
                    ]}
                  >
                    <Input.Password
                      prefix={<LockOutlined />}
                      placeholder="密码"
                      size="large"
                    />
                  </Form.Item>

                  <Form.Item
                    name="confirmPassword"
                    rules={[
                      { required: true, message: '请再次输入密码' },
                    ]}
                  >
                    <Input.Password
                      prefix={<LockOutlined />}
                      placeholder="确认密码"
                      size="large"
                    />
                  </Form.Item>

                  <Form.Item style={{ marginTop: 24 }}>
                    <Button
                      type="primary"
                      htmlType="submit"
                      loading={submitting}
                      size="large"
                      block
                    >
                      注册
                    </Button>
                  </Form.Item>
                </Form>
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
};

export default LoginPage;
